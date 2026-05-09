"""엑셀 시트 목록 확인"""
import argparse
import openpyxl

parser = argparse.ArgumentParser(description='시트 목록 확인')
parser.add_argument('--input', required=True, help='엑셀 파일 경로')
parser.add_argument('--out', required=True, help='출력 파일')
args = parser.parse_args()

wb = openpyxl.load_workbook(args.input, data_only=True)
with open(args.out, 'w', encoding='utf-8') as f:
    for i, name in enumerate(wb.sheetnames):
        f.write(f'{i}: {name}\n')
print('done')
