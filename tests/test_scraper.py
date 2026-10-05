"""Offline tests (no browser, no network). Run: python -m unittest discover tests"""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imdb_scraper import advanced, analysis, extractors, storage  # noqa: E402
from imdb_scraper.browser import PageContentError  # noqa: E402
from imdb_scraper.config import ADVANCED_COLUMNS, ADVANCED_SCHEMA, ADVANCED_STAGES, CREDIT_GROUPS, MERGED_SCHEMA  # noqa: E402
from imdb_scraper.parsing import split_listing_rank, title_id, title_url  # noqa: E402

LOG = logging.getLogger("tests")
ID = "tt0114709"


def title_props(**overrides):
    above = {
        "titleText": {"text": "Toy Story"}, "originalTitleText": {"text": "Toy Story"},
        "titleType": {"id": "movie"}, "releaseYear": {"year": 1995}, "isAdult": False,
        "productionStatus": {"currentProductionStage": {"id": "released"}},
        "plot": {"plotText": {"plainText": "A cowboy doll..."}}, "primaryImage": {"url": "https://x/y.jpg"},
        "certificate": {"rating": "G"}, "runtime": {"seconds": 4860},
        "ratingsSummary": {"aggregateRating": 8.3, "voteCount": 1202011},
        "metacritic": {"metascore": {"score": 96}}, "criticReviewsTotal": {"total": 175},
        "genres": {"genres": [{"text": "Animation"}, {"text": "Adventure"}]},
        "interests": {"edges": [{"node": {"primaryText": {"text": "Buddy Comedy"}}}]},
        "keywords": {"total": 360, "edges": [{"node": {"text": "toy"}}]},
    }
    main = {
        "releaseDate": {"day": 22, "month": 11, "year": 1995, "country": {"text": "United States"}},
        "ratingsSummary": {"topRanking": {"rank": 77}},
        "aggregateRatingsBreakdown": {"histogram": {"histogramValues": [{"rating": r, "voteCount": r * 10} for r in range(1, 11)]}},
        "reviews": {"total": 985}, "wins": {"total": 29}, "nominationsExcludeWins": {"total": 24},
        "prestigiousAwardSummary": {"wins": 0, "nominations": 3, "award": {"text": "Oscar"}},
        "countriesDetails": {"countries": [{"text": "United States"}]},
        "spokenLanguages": {"spokenLanguages": [{"text": "English"}]},
        "production": {"edges": [{"node": {"company": {"companyText": {"text": "Pixar"}}}}]},
        "filmingLocations": {"total": 1, "edges": [{"node": {"location": "Richmond, California, USA"}}]},
        "productionBudget": {"budget": {"amount": 30000000, "currency": "USD"}},
        "lifetimeGross": {"total": {"amount": 229947062, "currency": "USD"}},
        "worldwideGross": {"total": {"amount": 401157969, "currency": "USD"}},
        "openingWeekendGross": {"gross": {"total": {"amount": 29140617, "currency": "USD"}}, "weekendEndDate": "1995-11-26"},
        "moreLikeThisTitles": {"edges": [{"node": {"id": "tt0120363", "titleText": {"text": "Toy Story 2"}}}]},
    }
    above.update(overrides.pop("above", {}))
    main.update(overrides.pop("main", {}))
    return {"aboveTheFoldData": above, "mainColumnData": main}


class ParsingTests(unittest.TestCase):
    def test_ids_and_urls(self):
        self.assertEqual(title_id("https://www.imdb.com/title/tt0230794/?ref_=sr_i_3"), "tt0230794")
        self.assertEqual(title_url("tt0230794"), "https://www.imdb.com/title/tt0230794/")

    def test_rank_prefix(self):
        self.assertEqual(split_listing_rank("12. Foo"), (12, "Foo"))
        self.assertEqual(split_listing_rank("2001: A Space Odyssey"), (None, "2001: A Space Odyssey"))


class StorageTests(unittest.TestCase):
    def test_types_round_trip_exactly(self):
        schema = {"imdb_id": "str", "votes": "int", "rating": "float", "adult": "bool", "genres": "json", "severity": "str"}
        df = pd.DataFrame({
            "imdb_id": ["tt1", "tt2"], "votes": [1202011, None], "rating": [8.3, None],
            "adult": [False, None], "genres": [["Drama", "Réalisme"], []], "severity": ["none", None],
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            storage.write_csv_safely(df, path, schema)
            self.assertIn("1202011,8.3,False", path.read_text(encoding="utf-8"))  # no 1202011.0
            back = storage.read_csv_fast(path)
        self.assertEqual(back["votes"].tolist()[0], "1202011")
        self.assertTrue(pd.isna(back["votes"].iloc[1]))
        self.assertEqual(json.loads(back["genres"].iloc[0]), ["Drama", "Réalisme"])
        self.assertTrue(pd.isna(back["genres"].iloc[1]))  # an empty list is a blank cell
        self.assertEqual(back["severity"].iloc[0], "none")

    def test_read_drops_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            pd.DataFrame({"imdb_id": ["tt1", "tt1"], "v": ["a", "b"]}).to_csv(path, index=False)
            df = storage.read_csv_or_empty(path, {"imdb_id": "str", "v": "str"})
        self.assertEqual(df["v"].tolist(), ["b"])


class TitlePageTests(unittest.TestCase):
    def extract(self, **overrides):
        with mock.patch.object(extractors, "_page_props", return_value=title_props(**overrides)):
            return extractors.extract_title_page(None, ID)

    def test_fields(self):
        row = self.extract()
        self.assertEqual((row["title"], row["release_year"], row["runtime_seconds"]), ("Toy Story", 1995, 4860))
        self.assertEqual((row["release_date"], row["release_date_precision"]), ("1995-11-22", "day"))
        self.assertEqual((row["imdb_rating"], row["imdb_votes"], row["metascore"], row["top_rated_rank"]), (8.3, 1202011, 96, 77))
        self.assertEqual((row["user_reviews_count"], row["critic_reviews_count"]), (985, 175))
        self.assertEqual((row["budget_amount"], row["budget_currency"]), (30000000, "USD"))
        self.assertEqual((row["award_wins"], row["award_nominations"]), (29, 24))
        self.assertEqual(row["rating_histogram"], [r * 10 for r in range(1, 11)])
        self.assertEqual(row["genres"], ["Animation", "Adventure"])
        self.assertEqual(row["interests"], ["Buddy Comedy"])  # never mixed into genres
        self.assertEqual((row["similar_movie_ids"], row["similar_movies_status"]), (["tt0120363"], "found"))

    def test_no_awards_is_zero_and_missing_money_is_empty(self):
        row = self.extract(main={"wins": None, "nominationsExcludeWins": None, "productionBudget": None})
        self.assertEqual((row["award_wins"], row["award_nominations"]), (0, 0))
        self.assertIsNone(row["budget_amount"])

    def test_partial_release_dates(self):
        self.assertEqual(self.extract(main={"releaseDate": {"year": 1930}})["release_date_precision"], "year")
        self.assertEqual(self.extract(main={"releaseDate": {"year": 1930, "month": 5}})["release_date"], "1930-05")

    def test_missing_recommendations_section_fails(self):
        with self.assertRaises(PageContentError):
            self.extract(main={"moreLikeThisTitles": None})

    def test_invalid_values_fail_validation(self):
        with self.assertRaises(ValueError):
            self.extract(above={"ratingsSummary": {"aggregateRating": 11, "voteCount": 5}})
        with self.assertRaises(ValueError):
            self.extract(main={"productionBudget": {"budget": {"amount": 5, "currency": None}}})


class OtherStageTests(unittest.TestCase):
    def test_parental_severity_is_lowercase_and_none_is_kept(self):
        content = {
            "contentRatingData": {"categorySummaries": [{"title": "Sex & Nudity", "severitySummaryText": "None"}, {"title": "Profanity", "severitySummaryText": "Severe"}]},
            "certificates": [{"country": "Argentina", "ratings": [{"rating": "13", "extraInformation": ["original rating"]}]}],
        }
        with mock.patch.object(extractors, "_page_content_data", return_value=content):
            row = extractors.extract_parental_guide(None, ID)
        self.assertEqual((row["sex_nudity_severity"], row["profanity_severity"], row["violence_gore_severity"]), ("none", "severe", None))
        self.assertEqual(row["certificates_by_country"], [{"country": "Argentina", "rating": "13", "notes": "original rating"}])

    def test_parser_error_fails_stage(self):
        with mock.patch.object(extractors, "_page_content_data", return_value={"contentRatingData": {"categorySummaries": 5}}):
            with self.assertRaises(TypeError):
                extractors.extract_parental_guide(None, ID)

    def test_credit_groups_match_by_id_or_singular_plural_name(self):
        person = lambda n: {"id": f"nm{n}", "rowTitle": f"Person {n}", "characters": [f"Role {n}"]}
        categories = [
            {"id": "amzn1.imdb.concept.name_credit_category." + CREDIT_GROUPS["editors"]["id"], "name": "Editors", "section": {"items": [person(1)], "total": 1}},
            {"id": "other", "name": "Casting Director", "section": {"items": [person(2)], "total": 1}},
            {"id": "amzn1.imdb.concept.name_credit_group." + CREDIT_GROUPS["cast"]["id"], "name": "Cast", "section": {"items": [person(3), person(3), person(4)], "total": 5}},
        ]
        with mock.patch.object(extractors, "_page_content_data", return_value={"categories": categories}):
            row = extractors.extract_full_credits(None, ID)
        self.assertEqual(row["editors"], ["Person 1"])
        self.assertEqual(row["casting_directors_ids"], ["nm2"])
        self.assertEqual(row["cast"], ["Person 3", "Person 4"])  # duplicates removed
        self.assertEqual(row["cast_characters"], [["Role 3"], ["Role 4"]])
        self.assertEqual((row["cast_total"], row["credits_incomplete"]), (5, ["cast"]))
        self.assertIsNone(row["directors"])

    def test_release_info_entries_and_completeness(self):
        content = {"categories": [
            {"id": "releases", "section": {"total": 2, "items": [
                {"rowTitle": "United States", "listContent": [{"text": "November 22, 1995", "subText": "(premiere)"}]}]}},
            {"id": "akas", "section": {"total": 1, "items": [
                {"rowTitle": "Albania", "listContent": [{"text": "Bota e Lodrave", "subText": "(bootleg title)"}]}]}},
        ]}
        with mock.patch.object(extractors, "_page_content_data", return_value=content):
            row = extractors.extract_release_info(None, ID, complete=False)
        self.assertEqual(row["release_dates"], [{"country": "United States", "date": "1995-11-22", "note": "premiere"}])
        self.assertEqual(row["akas"], [{"country": "Albania", "title": "Bota e Lodrave", "note": "bootleg title"}])
        self.assertEqual(row["release_info_complete"], "preview")  # 1 of 2 releases listed
        with mock.patch.object(extractors, "_page_content_data", return_value={"categories": []}):
            self.assertEqual(extractors.extract_release_info(None, ID, complete=False)["release_info_complete"], "empty")

    def test_original_title_row_has_no_country(self):
        items = [{"rowTitle": "(original title)", "listContent": [{"text": "Toy Story", "subText": ""}]}]
        self.assertEqual(extractors._release_entries(items, "aka"), [{"country": None, "title": "Toy Story", "note": "original title"}])

    def test_iso_dates(self):
        self.assertEqual(extractors._iso_date("November 22, 1995"), "1995-11-22")
        self.assertEqual(extractors._iso_date("May 1995"), "1995-05")
        self.assertEqual(extractors._iso_date("1995"), "1995")
        self.assertEqual(extractors._iso_date("TBA"), "TBA")

    def test_failed_stage_keeps_previous_values(self):
        record = {"imdb_id": ID, "_stages": ["parental_guide", "full_credits"],
                  "_existing_row": {"composers": '["Old Composer"]', "profanity_severity": "mild"}}
        with mock.patch.object(extractors, "extract_parental_guide", return_value={"profanity_severity": "severe"}), \
                mock.patch.object(extractors, "extract_full_credits", side_effect=ValueError("boom")):
            with self.assertRaises(extractors.StageExtractionError) as ctx:
                extractors._extract_advanced_stages(None, record, {})
        exc = ctx.exception
        self.assertEqual((exc.stage, exc.remaining_stages), ("full_credits", ["full_credits"]))
        self.assertEqual(exc.partial_row["profanity_severity"], "severe")  # completed stage kept
        self.assertEqual(exc.partial_row["composers"], '["Old Composer"]')  # failed stage not erased


class AnalysisTests(unittest.TestCase):
    def test_derived_columns(self):
        df = pd.DataFrame({
            "release_year": ["1995", "1930", "1930"], "release_date": ["1995-11-22", "1930", "1930-05"],
            "release_date_precision": ["day", "year", "month"], "runtime_seconds": ["4860", None, None],
            "budget_amount": ["1000", "1000", "1000"], "budget_currency": ["USD", "DEM", "USD"],
            "gross_worldwide_amount": ["3000", "2000", None], "gross_worldwide_currency": ["USD", "USD", None],
            "genres": ['["a","b"]', None, "[]"], "cast": [None, None, None],
        })
        out = analysis.compute_derived_columns(df, LOG, LOG)
        self.assertEqual(out["runtime_minutes"].iloc[0], 81.0)
        self.assertEqual((out["gross_minus_budget"].iloc[0], out["gross_to_budget_ratio"].iloc[0]), (2000, 2.0))
        self.assertTrue(out["gross_minus_budget"].iloc[1:].isna().all())  # DEM vs USD: not comparable
        self.assertEqual(out["release_month"].iloc[0], 11)
        self.assertEqual(out["release_weekday"].iloc[0], "Wednesday")
        self.assertTrue(out["release_month"].iloc[1:2].isna().all())  # year-only date: month unknown
        self.assertEqual(out["release_month"].iloc[2], 5)
        self.assertTrue(pd.isna(out["release_weekday"].iloc[2]))
        self.assertEqual(out["genre_count"].iloc[0], 2)
        self.assertEqual(analysis._first_release_date('[{"date": "1996-01-02"}, {"date": "1995-11-19"}, {"date": "1995"}]'), "1995-11-19")
        self.assertIsNone(analysis._first_release_date('[{"date": "1995"}]'))
        self.assertTrue(pd.isna(out["genre_count"].iloc[1]))  # unknown, not zero
        formatted = storage.format_frame(out, MERGED_SCHEMA)
        self.assertEqual(str(formatted["release_decade"].dtype), "Int64")


class StatusTests(unittest.TestCase):
    def test_has_data(self):
        self.assertTrue(advanced._has_data("none"))  # a valid severity
        self.assertTrue(advanced._has_data("0"))
        self.assertFalse(advanced._has_data("[]"))
        self.assertFalse(advanced._has_data(None))

    def test_failed_stage_marks_link_failed_and_records_stages(self):
        partial = {column: None for column in ADVANCED_COLUMNS}
        partial.update(imdb_id=ID, composers='["Old Composer"]')
        error = extractors.StageExtractionError("full_credits", partial, ["full_credits", "release_info"], ValueError("boom"))
        status_records = {}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(advanced, "create_edge_driver", return_value=mock.Mock()), \
                mock.patch.object(advanced, "_extract_advanced_stages", side_effect=error):
            rows, failures = advanced._attempt_advanced_links(
                [{"imdb_id": ID, "title": "T"}], status_records, Path(tmp) / "attempts.jsonl", LOG, "initial", workers=1,
            )
        status = status_records[ID]
        self.assertEqual(status["status"], "failed")
        stages = json.loads(status["stage_status"])
        self.assertEqual((stages["title_page"]["status"], stages["parental_guide"]["status"]), ("completed", "completed"))
        self.assertEqual(stages["full_credits"]["status"], "failed")
        self.assertNotIn("release_info", stages)
        self.assertEqual(rows[0]["composers"], '["Old Composer"]')
        self.assertEqual(failures[0]["_stages"], ["full_credits", "release_info"])

    def test_success_marks_all_stages_completed(self):
        row = {column: None for column in ADVANCED_COLUMNS}
        row["imdb_id"] = ID
        status_records = {}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(advanced, "create_edge_driver", return_value=mock.Mock()), \
                mock.patch.object(advanced, "_extract_advanced_stages", return_value=row):
            advanced._attempt_advanced_links([{"imdb_id": ID, "title": "T"}], status_records, Path(tmp) / "a.jsonl", LOG, "initial", workers=1)
        status = status_records[ID]
        self.assertEqual(status["status"], "completed")
        self.assertEqual(set(json.loads(status["stage_status"])), set(ADVANCED_STAGES))

    def test_reconcile_with_history(self):
        other = "tt0000002"
        records = {ID: {"imdb_id": ID, "status": "completed"}, other: {"imdb_id": other, "status": "completed"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in [
                {"imdb_id": ID, "status": "completed"}, {"imdb_id": ID, "status": "failed", "error": "boom"},
                {"imdb_id": other, "status": "failed"}, {"imdb_id": other, "status": "completed"},
            ]), encoding="utf-8")
            self.assertEqual(advanced._reconcile_with_history(records, path), 1)
        self.assertEqual((records[ID]["status"], records[other]["status"]), ("failed", "completed"))

    def test_partial_row_is_not_complete(self):
        row = {column: None for column in ADVANCED_COLUMNS}
        row["genres"] = '["Drama"]'
        self.assertIn("parental_guide", advanced._missing_stages(row))

    def test_schema_has_unique_typed_columns(self):
        self.assertEqual(len(ADVANCED_COLUMNS), len(set(ADVANCED_COLUMNS)))
        self.assertTrue(set(ADVANCED_SCHEMA.values()) <= {"str", "int", "float", "bool", "json"})


if __name__ == "__main__":
    unittest.main()
