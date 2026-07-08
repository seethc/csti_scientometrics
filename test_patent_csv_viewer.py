import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from patent_csv_viewer import (
    AppState,
    PatentDataset,
    normalize_scope,
    priority_countries,
    row_matches_scope,
)


SAMPLE_CSV = """Display Key,Lens ID,Title,Abstract,Publication Year,Publication Date,Application Date,Earliest Priority Date,Jurisdiction,Document Type,Legal Status,Applicants,Inventors,Owners,CPC Classifications,IPCR Classifications,US Classifications,Simple Family Members,Simple Family Member Jurisdictions,Extended Family Members,Extended Family Member Jurisdictions,Priority Numbers,Cited Patents,Cited by Patent Count,Cites Patent Count,Simple Family Size,Extended Family Size,NPL Citation Count,URL
US-1,L1,Quantum photonic link,Optical interconnect for quantum computing,2024,2024-01-15,2022-02-03,2021-07-01,US,Granted Patent,ACTIVE,Example Inc,Ada Photon,Example Inc (2022-01-01),G02B6/12;;H04B10/80,G02B6/12,398/1,FAM1;;FAM2,US;;EP,EXT1;;EXT2,US;;EP,US 63/123;;PCT/EP2020/123,US-OLD;;EP-OLD,5,2,2,3,0,https://example.test/1
EP-2,L2,Photonic package,Packaging for optical qubits,2023,2023-06-02,2020-04-11,2019-09-20,EP,Patent Application,PENDING,Example GmbH,Ben Qubit,Example GmbH,G02B6/42,G02B6/42,385/1,FAM1;;FAM2,US;;EP,EXT1;;EXT2,US;;EP,EP 201234,US-OLD,1,4,2,3,1,https://example.test/2
JP-3,L3,Classical connector,Mechanical connector assembly,2020,2020-03-10,2018-01-01,2017-01-01,JP,Granted Patent,INACTIVE,Other Co,Chi Connector,Other Co,H01R13/00,H01R13/00,439/1,FAM3,JP,EXT3,JP,JP 20170001,JP-OLD,9,1,1,1,0,https://example.test/3
"""


def dataset() -> PatentDataset:
    data = PatentDataset(Path("__missing__.csv"))
    data.load_uploaded("sample.csv", SAMPLE_CSV.encode("utf-8"))
    return data


class PatentCsvViewerAnalysisTests(unittest.TestCase):
    def test_scope_matching_keywords_prefixes_and_filters(self) -> None:
        row = dataset().rows[0]
        scope = normalize_scope({
            "name": "QUPICS slice",
            "keywords": "quantum; photonic",
            "cpc": "G02B6",
            "ipcr": "G02B",
            "filters": {"jurisdiction": "US"},
        })
        self.assertTrue(row_matches_scope(row, scope))

        wrong_scope = normalize_scope({"name": "Wrong class", "keywords": "quantum", "cpc": "H01R"})
        self.assertFalse(row_matches_scope(row, wrong_scope))

    def test_priority_country_parsing(self) -> None:
        row = {"Priority Numbers": "US 63/123;;PCT/EP2020/123;;JP 20170001"}
        self.assertEqual(priority_countries(row), ["US", "EP", "JP"])

    def test_family_country_counts_are_deduplicated(self) -> None:
        data = dataset()
        counts = data.family_country_counter(data.rows[:2], "Simple Family Members", "Simple Family Member Jurisdictions")
        self.assertEqual(counts["US"], 1)
        self.assertEqual(counts["EP"], 1)

    def test_analysis_overlap_lag_and_lift(self) -> None:
        data = dataset()
        scopes = [
            normalize_scope({"name": "Photonic keyword", "keywords": "photonic"}),
            normalize_scope({"name": "G02B class", "cpc": "G02B"}),
        ]
        labels = {
            "L1": {"label": "relevant", "note": "", "updated": "2026-07-08 10:00"},
            "L2": {"label": "not_relevant", "note": "", "updated": "2026-07-08 10:01"},
        }
        analysis = data.analysis({}, scopes, labels)
        summaries = {item["id"]: item for item in analysis["scope_summaries"]}
        self.assertEqual(summaries["photonic_keyword"]["records"], 2)
        self.assertEqual(summaries["g02b_class"]["records"], 2)
        self.assertEqual(summaries["photonic_keyword"]["review"]["precision_pct"], 50.0)
        self.assertEqual(analysis["lag_timing"]["cutoffs"][1]["cutoff_year"], analysis["lag_timing"]["current_year"] - 2)
        self.assertTrue(analysis["classification_lift"]["photonic_keyword"])

    def test_lens_style_panels_include_expected_tables(self) -> None:
        data = dataset()
        panels = data.analysis({}, [], {})["lens_panels"]
        self.assertEqual(panels["timeline"][-1]["year"], 2024)
        self.assertEqual(panels["jurisdictions"][0]["count"], 1)
        self.assertEqual(panels["inventors"][0]["count"], 1)
        self.assertEqual(panels["top_cited_records"][0]["display_key"], "JP-3")
        self.assertEqual(panels["cited_patent_references"][0]["cited_patent"], "US-OLD")
        self.assertEqual(panels["cited_patent_references"][0]["count"], 2)

    def test_review_precision(self) -> None:
        data = dataset()
        labels = {
            "L1": {"label": "relevant", "note": "", "updated": ""},
            "L2": {"label": "uncertain", "note": "", "updated": ""},
            "L3": {"label": "not_relevant", "note": "", "updated": ""},
        }
        review = data.review_summary(data.rows, labels)
        self.assertEqual(review["reviewed"], 3)
        self.assertEqual(review["precision_pct"], 50.0)

    def test_app_state_saves_scopes_and_review_labels(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state = AppState(Path(tmpdir))
            scopes = state.save_scope({"name": "IPC slice", "ipcr": "G02B"})
            self.assertEqual(scopes[0]["id"], "ipc_slice")
            saved = state.save_label("L1", "relevant", "good match")
            self.assertEqual(saved["label"], "relevant")
            self.assertIn("good match", state.labels_csv().decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
