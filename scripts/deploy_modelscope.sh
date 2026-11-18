#!/usr/bin/env bash
set -euo pipefail

if [[ ${GITHUB_ACTIONS:-} != true ]]; then
    echo 'Run this deployment through GitHub Actions.'
    exit 1
fi

if [[ -z ${MODELSCOPE_TOKEN:-} ]]; then
    echo '::error::Configure the repository Actions secret MODELSCOPE_TOKEN.'
    exit 1
fi
source_root=$(git rev-parse --show-toplevel)
source_sha=$(git rev-parse HEAD)
remote=https://www.modelscope.cn/studios/MONTEC/BOM-Pilot.git
temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT
umask 077
unset GIT_TRACE GIT_TRACE_CURL GIT_TRACE_CURL_NO_DATA GIT_CURL_VERBOSE GIT_TRACE_PACKET \
    GIT_TRACE2 GIT_TRACE2_EVENT GIT_TRACE2_PERF
export GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false

# ModelScope SDK access tokens must be exchanged for a Git access token.
git_token=$(python - <<'PYTHON'
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


request = Request(
    "https://www.modelscope.cn/api/v1/login",
    data=json.dumps({"AccessToken": os.environ["MODELSCOPE_TOKEN"]}).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "BOM-Pilot-Deployment"},
    method="POST",
)
try:
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        payload = json.load(response)
    token = payload["Data"]["AccessToken"]
    if not isinstance(token, str) or not token or not token.isascii() or any(ch.isspace() for ch in token):
        raise ValueError
except HTTPError as exc:
    sys.exit(f"::error::ModelScope token exchange failed with HTTP {exc.code}.")
except (URLError, TimeoutError):
    sys.exit("::error::ModelScope token exchange could not reach the login endpoint.")
except (KeyError, TypeError, ValueError):
    sys.exit("::error::ModelScope login did not issue a Git token. Check the SDK access token.")
sys.stdout.write(token)
PYTHON
)
# GitHub intercepts this workflow command and masks the derived token.
printf '::add-mask::%s\n' "$git_token"
unset MODELSCOPE_TOKEN


# The helper returns credentials only to Git's credential pipe, for this exact URL.
# It neither persists credentials nor writes the token into the helper file.
cat > "$temp_dir/credential-helper" <<'HELPER'
#!/usr/bin/env bash
[[ ${1:-} == get ]] || exit 0
protocol= host= path=
while IFS='=' read -r field value && [[ -n $field ]]; do
    case "$field" in
        protocol) protocol=$value ;;
        host) host=$value ;;
        path) path=$value ;;
    esac
done
if [[ $protocol == https && $host == www.modelscope.cn && $path == studios/MONTEC/BOM-Pilot.git ]]; then
    printf 'username=oauth2\npassword=%s\n\n' "$MODELSCOPE_GIT_TOKEN"
fi
HELPER
chmod 700 "$temp_dir/credential-helper"

remote_git() {
    MODELSCOPE_GIT_TOKEN="$git_token" git -c credential.helper= -c "credential.helper=$temp_dir/credential-helper" \
        -c credential.useHttpPath=true -c http.followRedirects=false "$@"
}

target="$temp_dir/studio"
remote_git clone -- "$remote" "$target"
reference=$(git -C "$target" symbolic-ref refs/remotes/origin/HEAD)
[[ $reference == refs/remotes/origin/* ]] || exit 1
target_branch=${reference#refs/remotes/origin/}
[[ $(git -C "$target" symbolic-ref --short HEAD) == "$target_branch" ]] || exit 1
echo "ModelScope default branch: $target_branch"

python "$source_root/scripts/sync_modelscope.py" "$source_root" "$target"
git -C "$target" add --all
if git -C "$target" diff --cached --quiet; then
    echo 'ModelScope already has these deployment files.'
else
    git -C "$target" -c user.name='BOM Pilot deployment' -c user.email='actions@users.noreply.github.com' \
        commit -m "Deploy BOM Pilot from GitHub ${source_sha:0:12}"
    remote_git -C "$target" push --porcelain origin "HEAD:refs/heads/$target_branch"
fi

local_sha=$(git -C "$target" rev-parse HEAD)
remote_ref=$(remote_git -C "$target" ls-remote --exit-code origin "refs/heads/$target_branch")
[[ ${remote_ref%%$'\t'*} == "$local_sha" ]] || {
    echo '::error::ModelScope branch moved during verification.'
    exit 1
}
echo "Verified ModelScope commit: $local_sha"
