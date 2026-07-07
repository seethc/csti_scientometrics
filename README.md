# csti_scientometrics
Automation tools for my CSTI summer project

## Patent CSV viewer

Run the local patent viewer with:

```powershell
python .\patent_csv_viewer.py
```

Then open:

```text
http://127.0.0.1:8765
```

The opening dashboard counts publication records by patent office/country, de-duplicated simple-family country coverage, top applicants, top owners, legal status, and publication year.

The app defaults to:

```text
C:\Users\sugey\Dropbox\PC\Downloads\10yr-photonic-interconnects.csv
```

To use another CSV:

```powershell
python .\patent_csv_viewer.py --csv "C:\path\to\file.csv"
```
