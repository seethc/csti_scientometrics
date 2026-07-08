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

Use the **Open CSV** picker in the sidebar to load another export without restarting the app. The selected CSV is uploaded only to the local Python server running on your machine and is kept in memory for that session.

The viewer also extracts CPC, IPC, and USPC classifications and lets you filter by them. Use the **VOSviewer export** buttons in the sidebar to download raw files for the current filtered slice:

- `Corpus`: one patent title/abstract per line, for VOSviewer text mining.
- `Scores`: aligned numeric overlays such as publication year and citation counts.
- `Metadata`: line-by-line lookup back to Lens patent records.
- `Thesaurus`: optional patent boilerplate terms to ignore.

These exports do not calculate a network, layout, or clusters. In VOSviewer, use **Create a map based on text data**, select the corpus file, optionally select the scores and thesaurus files, and let VOSviewer calculate term extraction, co-occurrence, layout, and clustering itself.

Use the **Analysis** tab for simple Lens-style tables: patent documents over time, jurisdiction, family country coverage, priority-country proxy, document type, legal status, top applicants, top owners, top inventors, top CPC/IPC/USPC codes, and cited-patent tables. Each panel has a **Copy** button that copies tab-separated values for spreadsheet use.

The record detail pane includes manual labels for false-positive checking: relevant, not relevant, uncertain, plus an optional note. Labels are stored locally in `.patent_csv_viewer_state/`, which is ignored by git. You can export review labels as CSV from the Analysis tab.

You can also run the separate converter from the command line:

```powershell
python .\lens_to_vosviewer.py --csv "C:\path\to\lens-export.csv" --out-dir ".\vosviewer_exports"
```

This writes the same style of raw VOSviewer inputs:

- `*_vos_corpus.txt`: one patent title/abstract per line, for VOSviewer text mining.
- `*_vos_scores.txt`: aligned numeric scores such as publication year and citation counts.
- `*_vos_metadata.csv`: line-by-line lookup back to Lens patent records.
- `*_vos_README.txt`: import instructions for VOSviewer.

The app defaults to:

```text
C:\Users\sugey\Dropbox\PC\Downloads\10yr-photonic-interconnects.csv
```

To use another CSV:

```powershell
python .\patent_csv_viewer.py --csv "C:\path\to\file.csv"
```
