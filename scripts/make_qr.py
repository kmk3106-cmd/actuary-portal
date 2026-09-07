"""임의 URL/문자열을 QR PNG 로 생성한다 (segno, 순수 파이썬).

사용 예:
  python scripts/make_qr.py --url https://portal.kkuks.com/ --out qr-portal.png
  python scripts/make_qr.py --url https://portal.kkuks.com/ --out qr-portal.png --scale 8 --border 4
"""
import argparse

import segno


def main():
    ap = argparse.ArgumentParser(description='URL → QR PNG 생성')
    ap.add_argument('--url', required=True, help='QR 에 인코딩할 URL/문자열')
    ap.add_argument('--out', required=True, help='출력 PNG 경로')
    ap.add_argument('--scale', type=int, default=8, help='모듈 픽셀 배율 (기본 8)')
    ap.add_argument('--border', type=int, default=4, help='조용한 영역(quiet zone) 모듈 수 (기본 4)')
    ap.add_argument('--error', default='m', choices=['l', 'm', 'q', 'h'],
                    help='오류정정 레벨 l/m/q/h (기본 m)')
    args = ap.parse_args()

    qr = segno.make(args.url, error=args.error)
    qr.save(args.out, scale=args.scale, border=args.border)
    print('QR 생성 완료: {}  (url={})'.format(args.out, args.url))


if __name__ == '__main__':
    main()
