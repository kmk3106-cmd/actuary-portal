"""HTML 내 JS/CSS 자산의 ?v=N 캐시버스트 버전을 일괄 갱신한다.

규칙 14-3 대응: 공유 JS/CSS 수정 후 모든 HTML 의 ?v= 쿼리를 올려
브라우저 캐시로 인한 구버전 로딩을 방지한다.

사용 예:
  python scripts/bump_asset_version.py --root . --assets js/rbac.js,js/portal.js
  python scripts/bump_asset_version.py --root . --assets css/main.css --version 42
"""
import argparse
import glob
import os
import re
import sys


def find_max_version(html_files, asset):
    """현재 HTML 들에서 해당 asset 의 최대 ?v= 값을 찾는다 (없으면 0)."""
    pat = re.compile(re.escape(asset) + r'\?v=(\d+)')
    mx = 0
    for fp in html_files:
        with open(fp, 'r', encoding='utf-8') as f:
            for m in pat.finditer(f.read()):
                mx = max(mx, int(m.group(1)))
    return mx


def bump_asset(html_files, asset, new_version):
    """asset 참조를 모두 ?v=new_version 으로 치환. (버전 없던 것도 부여)"""
    # "js/portal.js" 또는 "js/portal.js?v=29" 형태를 모두 잡아 교체
    pat = re.compile(re.escape(asset) + r'(\?v=\d+)?(?=["\'])')
    replacement = '{}?v={}'.format(asset, new_version)
    changed = 0
    for fp in html_files:
        with open(fp, 'r', encoding='utf-8') as f:
            src = f.read()
        new_src, n = pat.subn(replacement, src)
        if n and new_src != src:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new_src)
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser(description='HTML 자산 캐시버스트 버전 일괄 갱신')
    ap.add_argument('--root', required=True, help='HTML 루트 폴더')
    ap.add_argument('--assets', required=True,
                    help='대상 자산 경로 콤마구분 (예: js/rbac.js,js/portal.js)')
    ap.add_argument('--version', type=int, default=None,
                    help='지정 버전. 생략 시 (모든 대상 자산의 현재 최대값+1) 사용')
    ap.add_argument('--glob', default='*.html', help='HTML 매칭 패턴 (기본 *.html)')
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    html_files = sorted(glob.glob(os.path.join(root, args.glob)))
    if not html_files:
        print('대상 HTML 없음:', os.path.join(root, args.glob))
        sys.exit(1)

    assets = [a.strip() for a in args.assets.split(',') if a.strip()]

    if args.version is not None:
        new_version = args.version
    else:
        cur_max = max((find_max_version(html_files, a) for a in assets), default=0)
        new_version = cur_max + 1

    print('대상 HTML {}개, 새 버전 = v{}'.format(len(html_files), new_version))
    for a in assets:
        cnt = bump_asset(html_files, a, new_version)
        print('  {} -> ?v={}  ({}개 파일 갱신)'.format(a, new_version, cnt))


if __name__ == '__main__':
    main()
