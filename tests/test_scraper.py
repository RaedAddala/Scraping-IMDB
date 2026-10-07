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

from imdb_scraper import advanced, analysis, extractors, metadata, pipeline, quality, storage  # noqa: E402
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


    def test_release_month_and_weekday_use_the_earliest_release_not_a_later_regional_one(self):
        df = pd.DataFrame({
            "release_year": ["1920", "1920", "1920"],
            "release_date": ["1979-11-08", "1920-05-04", "1921-02-10"],  # regional dates: re-release / same year / next year
            "release_dates": ['[{"date": "1920-02-02"}]', None, None],
            "title": ["A", "B", "C"],
        })
        out = analysis.compute_derived_columns(df, LOG, LOG)
        self.assertEqual(out["release_month"].tolist()[:2], [2, 5])
        self.assertEqual(out["release_weekday"].tolist()[:2], ["Monday", "Tuesday"])
        self.assertTrue(pd.isna(out["release_month"].iloc[2]) and pd.isna(out["release_weekday"].iloc[2]))  # 1921 date is not in 1920

    def test_language_none_placeholder_is_not_counted(self):
        self.assertEqual(analysis._language_len('["None"]'), 0)
        self.assertEqual(analysis._language_len('["None", "English"]'), 1)
        self.assertTrue(pd.isna(analysis._language_len(None)))

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
        self.assertIsNone(row["certificates_total"])

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


class SavedDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(storage, "SCRIPT_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_only_the_merged_csv_is_in_data_and_state_is_in_logs(self):
        paths = storage.year_paths(1995)
        self.assertEqual(paths["merged"].parent.parent.name, "Data")
        for key in ("status", "attempts"):
            self.assertEqual(paths[key].parent.parent.name, "Logs")
        self.assertNotIn("basic", paths)

    def test_save_and_load_merged_round_trip(self):
        listing = pd.DataFrame({"imdb_id": ["tt1", "tt2"], "search_year": [1995, 1995], "listing_rank": [1, 2], "listing_title": ["A", "B"]})
        details = pd.DataFrame([{"imdb_id": "tt1", "title": "A", "imdb_votes": 1202011, "genres": ["Drama"], "budget_amount": 10, "budget_currency": "USD",
                                 "gross_worldwide_amount": 30, "gross_worldwide_currency": "USD"}])
        analysis.save_merged(1995, listing, details, LOG, LOG)
        text = storage.year_paths(1995)["merged"].read_text(encoding="utf-8")
        self.assertIn("1202011", text)
        self.assertNotIn("1202011.0", text)
        loaded_listing, loaded_details = analysis.load_merged(1995)
        self.assertEqual(loaded_listing["imdb_id"].tolist(), ["tt1", "tt2"])
        self.assertEqual(loaded_details.set_index("imdb_id").loc["tt1", "title"], "A")
        self.assertTrue(pd.isna(loaded_details.set_index("imdb_id").loc["tt2", "title"]))
        self.assertEqual(analysis.load_merged(2001)[0], None)

    def test_listing_never_shrinks_from_partial_or_limited_scrapes(self):
        existing = pd.DataFrame({"imdb_id": [f"tt{i}" for i in range(10)]})
        small = pd.DataFrame({"imdb_id": ["tt1", "tt2"]})
        small.attrs["complete"] = True
        self.assertIs(pipeline._choose_listing(small, existing, 2, LOG, LOG), existing)  # limit reached
        self.assertIs(pipeline._choose_listing(small, existing, 1000, LOG, LOG), small)  # genuinely smaller
        small.attrs["complete"] = False
        self.assertIs(pipeline._choose_listing(small, existing, 1000, LOG, LOG), existing)  # incomplete


    def test_timestamps_and_numbers_are_not_rewritten_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            path.write_text("imdb_id,scraped_at,ratio,code" + chr(10) + "tt1,2026-10-05T19:35:20+00:00,2.10,007" + chr(10), encoding="utf-8")
            row = storage.read_csv_fast(path).iloc[0]
        self.assertEqual((row["scraped_at"], row["ratio"], row["code"]), ("2026-10-05T19:35:20+00:00", "2.10", "007"))

    def test_derived_counts_do_not_depend_on_whether_lists_come_from_memory_or_csv(self):
        in_memory = pd.DataFrame({"title": ["A"], "genres": [[]], "languages": [["English"]], "countries_of_origin": [[]]})
        from_csv = pd.DataFrame({"title": ["A"], "genres": [None], "languages": ['["English"]'], "countries_of_origin": [None]})
        schema = {"title": "str", "genres": "json", "languages": "json", "countries_of_origin": "json"}
        results = [analysis.compute_derived_columns(storage.format_frame(df, schema), LOG, LOG) for df in (in_memory, from_csv)]
        for out in results:
            self.assertEqual((out["genre_count"].iloc[0], out["language_count"].iloc[0], out["country_count"].iloc[0]), (0, 1, 0))


class QualityTests(unittest.TestCase):
    def good_row(self):
        row = {column: None for column in MERGED_SCHEMA}
        row.update(imdb_id=ID, title="T", imdb_rating="8.3", imdb_votes="100", metascore="50", budget_amount="5", budget_currency="USD",
                   rating_histogram=json.dumps([10] * 10), cast=json.dumps(["A"]), cast_ids=json.dumps(["nm0000001"]),
                   cast_characters=json.dumps([["X"]]), cast_total="1", similar_movie_ids=json.dumps(["tt0120363"]), similar_movie_titles=json.dumps(["B"]),
                   release_date="1995-11-22")
        return row

    def test_clean_row_has_no_issues(self):
        self.assertEqual(quality.row_issues(self.good_row()), [])

    def test_each_rule_catches_its_violation(self):
        cases = {
            "imdb_id_format": {"imdb_id": "123"},
            "rating_out_of_range": {"imdb_rating": "11"},
            "money_without_currency": {"budget_currency": None},
            "credit_ids_misaligned": {"cast_ids": json.dumps(["nm0000001", "nm0000002"])},
            "cast_inconsistent": {"cast_total": "0"},
            "similar_movies_inconsistent": {"similar_movie_titles": json.dumps([])},
            "histogram_vs_votes": {"imdb_votes": "5000"},
            "invalid_date": {"release_date": "1995-13-40"},
            "invalid_json": {"genres": "not json"},
        }
        for rule, change in cases.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, quality.row_issues({**self.good_row(), **change}))

    def test_check_quality_skips_unscraped_rows(self):
        frame = pd.DataFrame([self.good_row(), {**self.good_row(), "imdb_id": "tt0000002", "title": None, "imdb_rating": "99"}])
        self.assertEqual(quality.check_quality(frame), {})


class RobustnessTests(unittest.TestCase):
    def test_year_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(storage, "SCRIPT_DIR", Path(tmp)):
            with storage.year_lock(1995):
                with self.assertRaises(RuntimeError):
                    with storage.year_lock(1995):
                        pass
                with storage.year_lock(1996):  # other years are independent
                    pass
            with storage.year_lock(1995):  # released afterwards
                pass

    def test_month_names_do_not_depend_on_locale(self):
        self.assertEqual(extractors._iso_date("March 5, 1930"), "1930-03-05")
        self.assertEqual(extractors._iso_date("September 1930"), "1930-09")
        self.assertEqual(extractors._iso_date("Spring 1930"), "Spring 1930")
        self.assertEqual(extractors._iso_date("Foo 5, 1930"), "Foo 5, 1930")

    def test_write_fails_clearly_when_file_is_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            with mock.patch.object(Path, "replace", side_effect=PermissionError), mock.patch.object(storage.time, "sleep"):
                with self.assertRaises(PermissionError) as ctx:
                    storage.write_csv_safely(pd.DataFrame({"a": [1]}), path)
        self.assertIn("close it", str(ctx.exception))


class ReleasePaginationTests(unittest.TestCase):
    def node(self, country, date, attributes=()):
        return {"country": {"text": country}, "displayableProperty": {"value": {"plainText": date}}, "attributes": [{"text": t} for t in attributes]}

    def test_release_rows_match_the_page_shape(self):
        item = extractors._release_node_to_item("releases", self.node("Italy", "September 6, 2009", ["3-D version", "re-release"]))
        self.assertEqual(extractors._release_entries([item], "release"), [{"country": "Italy", "date": "2009-09-06", "note": "3-D version, re-release"}])

    def test_aka_rows_list_language_before_qualifiers(self):
        node = {"country": {"text": "Japan"}, "language": {"text": "English"},
                "displayableProperty": {"value": {"plainText": "Spirited Away"}, "qualifiersInMarkdownList": [{"plainText": "Alternative Title"}]}}
        item = extractors._release_node_to_item("akas", node)
        self.assertEqual(extractors._release_entries([item], "aka"), [{"country": "Japan", "title": "Spirited Away", "note": "English, Alternative Title"}])

    def test_pages_are_followed_until_the_total_is_reached(self):
        pages = [
            {"data": {"title": {"releaseDates": {"edges": [{"node": self.node("A", "1995")}] * 50, "pageInfo": {"endCursor": "c2", "hasNextPage": True}}}}},
            {"data": {"title": {"releaseDates": {"edges": [{"node": self.node("B", "1996")}] * 8, "pageInfo": {"endCursor": "c3", "hasNextPage": False}}}}},
        ]
        driver = mock.Mock()
        driver.execute_async_script.side_effect = pages
        rows = extractors._fetch_remaining_rows(driver, ID, "releases", 5, 63, "c1")
        self.assertEqual(len(rows), 58)
        self.assertIn("after%22%3A%22c2", driver.execute_async_script.call_args_list[1].args[1])  # second call used the cursor from the first

    def test_unexpected_answer_raises(self):
        driver = mock.Mock()
        driver.execute_async_script.return_value = {"errors": [{"message": "PersistedQueryNotFound"}]}
        with self.assertRaises(PageContentError):
            extractors._fetch_remaining_rows(driver, ID, "releases", 5, 63, "c1")

    def test_falls_back_to_page_expansion_when_graphql_fails(self):
        content = {"categories": [
            {"id": "releases", "section": {"total": 2, "endCursor": "c", "items": [{"rowTitle": "A", "listContent": [{"text": "1995", "subText": ""}]}]}},
            {"id": "akas", "section": {"total": 0, "items": []}},
        ]}
        expanded = {"releases": [{"rowTitle": "A", "listContent": [{"text": "1995", "subText": ""}]}, {"rowTitle": "B", "listContent": [{"text": "1996", "subText": ""}]}]}
        timings = {}
        with mock.patch.object(extractors, "_page_content_data", return_value=content),                 mock.patch.object(extractors, "_fetch_remaining_rows", side_effect=PageContentError("changed")),                 mock.patch.object(extractors, "_expand_release_info", return_value=expanded):
            row = extractors.extract_release_info(None, ID, timings=timings, complete=True)
        self.assertEqual([e["country"] for e in row["release_dates"]], ["A", "B"])
        self.assertTrue(timings["release_info_fallback"])
        self.assertEqual(row["release_info_complete"], "complete")


class ReleaseCompletenessTests(unittest.TestCase):
    def test_rows_without_a_country_are_kept(self):
        items = [{"rowTitle": "", "listContent": [{"text": "Some Title", "subText": "(working title)"}]},
                 {"rowTitle": "France", "listContent": [{"text": "Un titre", "subText": ""}]}]
        self.assertEqual(extractors._release_entries(items, "aka"), [
            {"country": None, "title": "Some Title", "note": "working title"}, {"country": "France", "title": "Un titre", "note": None}])

    def content(self, rows, total):
        return {"categories": [{"id": "releases", "section": {"total": 0, "items": []}},
                               {"id": "akas", "section": {"total": total, "endCursor": "c", "items": rows}}]}

    def test_a_list_shorter_than_its_total_is_a_preview_not_complete(self):
        rows = [{"rowTitle": "France", "listContent": [{"text": "Un titre", "subText": ""}]}]
        with mock.patch.object(extractors, "_page_content_data", return_value=self.content(rows, 3)),                 mock.patch.object(extractors, "_fetch_remaining_rows", return_value=[]),                 mock.patch.object(extractors, "_expand_release_info", return_value={}):
            timings = {}
            row = extractors.extract_release_info(None, ID, timings=timings, complete=True)
        self.assertEqual(row["release_info_complete"], "preview")
        self.assertTrue(timings["release_info_fallback"])  # short after GraphQL: the page's own expansion was tried too

    def test_rows_dropped_for_having_no_text_no_longer_count_towards_complete(self):
        rows = [{"rowTitle": "France", "listContent": []}, {"rowTitle": "Italy", "listContent": [{"text": "Il titolo", "subText": ""}]}]
        with mock.patch.object(extractors, "_page_content_data", return_value=self.content(rows, 2)),                 mock.patch.object(extractors, "_fetch_remaining_rows", return_value=[]),                 mock.patch.object(extractors, "_expand_release_info", return_value={}):
            row = extractors.extract_release_info(None, ID, complete=True)
        self.assertEqual(row["release_info_complete"], "preview")  # 1 entry saved for 2 reported rows


class RepairTests(unittest.TestCase):
    def test_titles_to_repair_maps_rules_to_stages(self):
        good = {column: None for column in MERGED_SCHEMA}
        good.update(imdb_id=ID, title="T", release_info_complete="complete", release_dates_total="3",
                    release_dates=json.dumps([{"country": "A", "date": "1995", "note": None}]))
        fine = {**good, "imdb_id": "tt0000002", "release_dates_total": "1"}
        self.assertEqual(quality.titles_to_repair(pd.DataFrame([good, fine])), {ID: ["release_info"]})

    def test_only_listed_titles_and_stages_are_scraped(self):
        listing = pd.DataFrame({"imdb_id": [ID, "tt0000002"], "search_year": [1995, 1995], "listing_rank": [1, 2], "listing_title": ["A", "B"]})
        seen = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(storage, "SCRIPT_DIR", Path(tmp)),                 mock.patch.object(advanced, "_attempt_advanced_links", side_effect=lambda recs, *a, **k: (seen.extend(recs), ([], []))[1]):
            advanced.extract_advanced_data(1995, listing, LOG, LOG, stages_by_id={ID: ["release_info"]})
        self.assertEqual([(r["imdb_id"], r["_stages"]) for r in seen], [(ID, ["release_info"])])


class CreditPaginationTests(unittest.TestCase):
    def person(self, n):
        return {"node": {"name": {"id": f"nm{n:07d}", "nameText": {"text": f"Person {n}"}}}}

    def category(self, total, shown):
        return {"id": "amzn1.imdb.concept.name_credit_category." + CREDIT_GROUPS["cinematographers"]["id"], "name": "Cinematographers",
                "section": {"total": total, "endCursor": "c1", "items": [{"id": f"nm{n:07d}", "rowTitle": f"Person {n}", "characters": []} for n in range(1, shown + 1)]}}

    def test_remaining_people_are_appended_in_order(self):
        driver = mock.Mock()
        driver.execute_async_script.return_value = {"data": {"title": {"creditsV2": {"edges": [self.person(n) for n in range(11, 20)], "pageInfo": {"hasNextPage": False}}}}}
        with mock.patch.object(extractors, "_page_content_data", return_value={"categories": [self.category(19, 10)]}):
            row = extractors.extract_full_credits(driver, ID)
        self.assertEqual(len(row["cinematographers"]), 19)
        self.assertEqual(row["cinematographers"][10], "Person 11")
        self.assertEqual(len(row["cinematographers_ids"]), 19)
        self.assertIsNone(row["credits_incomplete"])
        self.assertIn("category%22%3A%22amzn1", driver.execute_async_script.call_args.args[1])

    def test_failed_pagination_keeps_what_the_page_lists_and_flags_the_group(self):
        driver = mock.Mock()
        driver.execute_async_script.return_value = {"errors": [{"message": "PersistedQueryNotFound"}]}
        with mock.patch.object(extractors, "_page_content_data", return_value={"categories": [self.category(19, 10)]}):
            row = extractors.extract_full_credits(driver, ID)
        self.assertEqual(len(row["cinematographers"]), 10)
        self.assertEqual(row["credits_incomplete"], ["cinematographers"])


class QualityRepairRuleTests(unittest.TestCase):
    def test_incomplete_credits_and_previews_are_flagged_and_repairable(self):
        row = {column: None for column in MERGED_SCHEMA}
        row.update(imdb_id=ID, title="T", credits_incomplete=json.dumps(["composers"]), release_info_complete="preview")
        issues = quality.row_issues(row)
        self.assertIn("credit_group_incomplete", issues)
        self.assertIn("release_info_incomplete", issues)
        self.assertEqual(quality.titles_to_repair(pd.DataFrame([row])), {ID: ["full_credits", "release_info"]})


class ScriptlessLoadTests(unittest.TestCase):
    def test_refused_scriptless_load_retries_once_with_scripts_then_returns(self):
        modes = []
        loads = iter([({}, False, False), ({"contentData": {"x": 1}}, True, False)])
        with mock.patch.object(extractors, "set_script_mode", side_effect=lambda d, allowed: modes.append(allowed)),                 mock.patch.object(extractors, "_load_props", side_effect=lambda *a: next(loads)):
            props = extractors._page_props(None, "https://www.imdb.com/title/tt0114709/", stage="parental_guide")
        self.assertEqual(modes, [False, True])
        self.assertEqual(props["contentData"], {"x": 1})

    def test_still_refused_after_the_retry_fails_the_stage(self):
        with mock.patch.object(extractors, "set_script_mode"), mock.patch.object(extractors, "_load_props", return_value=({}, False, False)):
            with self.assertRaises(PageContentError):
                extractors._page_props(None, "https://www.imdb.com/title/tt0114709/", stage="parental_guide")

    def test_worker_count_is_capped_at_the_configured_maximum(self):
        from imdb_scraper.config import ADVANCED_WORKERS, MAX_WORKERS
        self.assertLessEqual(ADVANCED_WORKERS, MAX_WORKERS)


class StopAndResumeTests(unittest.TestCase):
    def records(self, n):
        return [{"imdb_id": f"tt{i:07d}", "title": f"T{i}"} for i in range(1, n + 1)]

    def test_stops_early_after_consecutive_failures_and_leaves_rest_retryable(self):
        status_records, run_state = {}, {}
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(advanced, "MAX_CONSECUTIVE_FAILURES", 3), mock.patch.object(advanced, "NETWORK_BACKOFF_SECONDS", 0), mock.patch.object(advanced, "create_edge_driver", return_value=mock.Mock()),                 mock.patch.object(advanced, "_extract_advanced_stages", side_effect=PageContentError("blocked")):
            rows, failures = advanced._attempt_advanced_links(
                self.records(12), status_records, Path(tmp) / "a.jsonl", LOG, "initial", workers=1, run_state=run_state)
        self.assertIn("in a row failed", run_state["stopped_early"])
        self.assertEqual(len(failures), 3)  # only titles actually attempted are failures
        untouched = [s for s in status_records.values() if s["status"] == "pending"]
        self.assertEqual(len(untouched), 9)  # the rest stay pending, with no attempt counted
        self.assertTrue(all(s["attempt_count"] == 0 for s in untouched))

    def test_interrupt_saves_progress_so_far(self):
        status_records, saved = {}, []
        row = {column: None for column in ADVANCED_COLUMNS}
        row["imdb_id"] = "tt0000001"
        calls = {"n": 0}

        def log(path, event):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(advanced, "create_edge_driver", return_value=mock.Mock()),                 mock.patch.object(advanced, "_extract_advanced_stages", return_value=row),                 mock.patch.object(advanced, "append_attempt_log", side_effect=log):
            with self.assertRaises(KeyboardInterrupt):
                advanced._attempt_advanced_links(self.records(5), status_records, Path(tmp) / "a.jsonl", LOG, "initial",
                                                 workers=1, checkpoint=lambda rows: saved.append(len(rows)))
        self.assertEqual(saved[-1], 2)  # the two titles finished before Ctrl+C


class LoggingTests(unittest.TestCase):
    def test_errors_are_one_short_line(self):
        long = "Message: element not interactable" + chr(10) + "  (Session info: msedge=1)" + chr(10) + "Stacktrace:" + chr(10) + chr(10).join(f"frame {n}" for n in range(50))
        text = storage.describe_error(RuntimeError(long))
        self.assertEqual(text, "RuntimeError: element not interactable")
        self.assertLessEqual(len(storage.describe_error(ValueError("x" * 1000))), 175)

    def test_attempt_events_have_stage_seconds_only(self):
        self.assertEqual(advanced._stage_seconds({"title_page_seconds": 3.2, "title_page_content_ready": True, "release_info_expansion_seconds": 8.0}), {"title_page": 3.2})


class MetadataTests(unittest.TestCase):
    def write_year(self, data, year, header=None):
        (data / str(year)).mkdir(exist_ok=True)
        path = data / str(year) / f"merged_movies_data_{year}.csv"
        path.write_text(",".join(header or list(MERGED_SCHEMA)) + chr(10), encoding="utf-8")
        return path

    def test_every_column_is_documented_with_a_supported_type(self):
        fields = metadata.schema_fields()
        self.assertEqual([f["name"] for f in fields], list(MERGED_SCHEMA))  # same order as the CSV
        self.assertTrue(all(f["description"].strip() and f["type"] in metadata.KAGGLE_TYPES for f in fields))
        self.assertEqual(set(metadata.COLUMN_METADATA), set(MERGED_SCHEMA))  # nothing missing, nothing invented

    def test_types_follow_meaning_and_fit_the_csv_kind(self):
        types = {f["name"]: f["type"] for f in metadata.schema_fields()}
        self.assertEqual((types["imdb_id"], types["poster_url"], types["scraped_at"], types["is_adult"]), ("id", "url", "datetime", "boolean"))
        self.assertEqual((types["imdb_rating"], types["imdb_votes"], types["genres"]), ("decimal", "integer", "string"))

    def test_metadata_is_deterministic_and_lists_one_resource_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.write_year(data, 1995)
            self.write_year(data, 1920)
            path, count = metadata.write_dataset_metadata(data)
            first = path.read_text(encoding="utf-8")
            metadata.write_dataset_metadata(data)
            self.assertEqual(first, path.read_text(encoding="utf-8"))
        written = json.loads(first)
        self.assertEqual(count, 2)
        self.assertEqual([r["path"] for r in written["resources"]], ["1920/merged_movies_data_1920.csv", "1995/merged_movies_data_1995.csv"])
        self.assertTrue(all("title" not in field for r in written["resources"] for field in r["schema"]["fields"]))  # description, not legacy title

    def test_validation_catches_each_kind_of_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.write_year(data, 1995)
            good = metadata.build_metadata(data)
            metadata.validate_metadata(good, data)
            cases = {
                "different order": lambda m: m["resources"][0]["schema"]["fields"].reverse(),
                "missing column": lambda m: m["resources"][0]["schema"]["fields"].pop(),
                "extra column": lambda m: m["resources"][0]["schema"]["fields"].append({"name": "ghost", "description": "x", "type": "string"}),
                "empty description": lambda m: m["resources"][0]["schema"]["fields"][0].update(description=" "),
                "unsupported type": lambda m: m["resources"][0]["schema"]["fields"][0].update(type="text"),
                "type vs kind": lambda m: m["resources"][0]["schema"]["fields"][1].update(type="boolean"),
                "missing file": lambda m: m["resources"][0].update(path="1999/merged_movies_data_1999.csv"),
                "undocumented file": lambda m: m["resources"].clear(),
            }
            for name, break_it in cases.items():
                with self.subTest(name):
                    broken = json.loads(json.dumps(good))
                    break_it(broken)
                    with self.assertRaises(ValueError):
                        metadata.validate_metadata(broken, data)
            self.write_year(data, 2001, header=["imdb_id", "other"])  # a CSV that does not follow the schema
            with self.assertRaises(ValueError):
                metadata.write_dataset_metadata(data)


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
