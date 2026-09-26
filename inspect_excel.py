import openpyxl

try:
    wb = openpyxl.load_workbook('backup_diemdanh.xlsx')
    sheet = wb.active
    
    print("Columns:")
    headers = []
    for cell in sheet[1]:
        headers.append(cell.value)
        print(f" - {cell.value}")
        
    print("\nFirst 3 rows:")
    for row in sheet.iter_rows(min_row=2, max_row=4, values_only=True):
        print(row)

except Exception as e:
    print(f"Error: {e}")
