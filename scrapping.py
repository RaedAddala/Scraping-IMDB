import os
import time
import logging
import argparse
import pandas as pd
from datetime import datetime

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def clean_text(element):
    """Return stripped text from a BeautifulSoup element."""
    return element.get_text(strip=True) if element else None


def create_edge_driver():
    driver_path = "edgedriver.exe"
    options = webdriver.EdgeOptions()
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 "
        "Safari/537.36 Edg/121.0.0.0"
    )
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--log-level=3")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")

    service = Service(executable_path=driver_path)
    driver = webdriver.Edge(service=service, options=options)
    driver.set_window_size(800, 600)
    return driver


def extract_listing_metadata(film):
    metadata_items = film.select(".dli-title-metadata li.ipc-inline-list__item")
    metadata = [clean_text(item) for item in metadata_items]

    year_data = metadata[0] if len(metadata) > 0 else None
    duration = metadata[1] if len(metadata) > 1 else None
    mpa = metadata[2] if len(metadata) > 2 else None

    return year_data, duration, mpa


def setup_directories(year):
    """Create the output directory structure for a specific year."""
    data_dir = f"Data/{year}"
    os.makedirs(data_dir, exist_ok=True)

    logs_dir = f"Logs/{year}"
    os.makedirs(logs_dir, exist_ok=True)

    return data_dir, logs_dir


def setup_logging(year):
    """Configure error and result loggers for a specific year."""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    error_logger = logging.getLogger(f"error_logger_{year}")
    error_logger.setLevel(logging.ERROR)

    error_handler = logging.FileHandler(f"Logs/{year}/errors.txt")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    error_logger.addHandler(error_handler)

    results_logger = logging.getLogger(f"results_logger_{year}")
    results_logger.setLevel(logging.INFO)

    results_handler = logging.FileHandler(f"Logs/{year}/results.txt")
    results_handler.setLevel(logging.INFO)
    results_handler.setFormatter(formatter)

    results_logger.addHandler(results_handler)

    return error_logger, results_logger


def extract_links(year, error_logger, results_logger, max_movies=600):
    """Extract movie links and basic data from IMDb for a specific year."""
    start_time = time.time()

    results_logger.info(f"Starting link extraction for year {year}")

    url = f"https://www.imdb.com/search/title/?title_type=feature&release_date={year}-01-01,{year}-12-31&count=50&sort=boxoffice_gross_us,desc"

    driver = create_edge_driver()

    films_data = []
    errors_count = 0

    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.ipc-metadata-list"))
        )

        loaded_data = len(driver.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"))
        failed_load_attempts = 0
        while loaded_data < max_movies and failed_load_attempts < 3:
            try:
                load_more_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//button[contains(@class, 'ipc-btn') and .//span[contains(text(), '50 more')]]",
                        )
                    )
                )

                driver.execute_script(
                    "arguments[0].scrollIntoView(true);", load_more_button
                )
                driver.execute_script("arguments[0].click();", load_more_button)

                WebDriverWait(driver, 15).until(
                    lambda active_driver: len(
                        active_driver.find_elements(
                            By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"
                        )
                    )
                    > loaded_data
                )
                loaded_data = len(
                    driver.find_elements(
                        By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"
                    )
                )
                failed_load_attempts = 0

            except Exception as e:
                failed_load_attempts += 1
                error_logger.error(
                    f"Load more attempt {failed_load_attempts} failed after "
                    f"{loaded_data} loaded items: {e}"
                )
                time.sleep(2)

        results_logger.info(f"Loaded {loaded_data} items before stopping")

        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")
        del html

        films = soup.select("ul.ipc-metadata-list")
        if films and len(films) > 0:
            films = films[0]
            results_logger.info(
                f"Found film list container: {films.name}, classes: {films.get('class')}"
            )

        if films:
            for film in films.find_all("li", class_="ipc-metadata-list-summary-item")[
                :max_movies
            ]:
                try:
                    title_tag = film.select_one("a.ipc-title-link-wrapper")
                    title = clean_text(title_tag)
                    year_data, duration, mpa = extract_listing_metadata(film)

                    rating_info = film.find("span", class_="ipc-rating-star--rating")
                    rating = clean_text(rating_info)

                    link_tag = film.select_one("a.ipc-lockup-overlay[href]")
                    movie_link = (
                        f"https://www.imdb.com{link_tag['href']}" if link_tag else None
                    )

                    vote_count_info = film.find(
                        "span", class_="ipc-rating-star--voteCount"
                    )
                    vote_count = (
                        vote_count_info.text.strip().replace("\xa0", "")[1:-1]
                        if vote_count_info
                        else None
                    )

                    meta_score_info = film.find("span", class_="metacritic-score-box")
                    meta_score = clean_text(meta_score_info)

                    description_div = film.find(
                        "div", class_="ipc-html-content-inner-div"
                    )
                    description = clean_text(description_div)

                    films_data.append(
                        {
                            "Title": title,
                            "Year": year_data,
                            "Duration": duration,
                            "MPA": mpa,
                            "Rating": rating,
                            "Votes": vote_count,
                            "meta_score": meta_score,
                            "description": description,
                            "Movie Link": movie_link,
                        }
                    )

                except Exception as e:
                    error_logger.error(f"Error extracting data for a film: {e}")
                    errors_count += 1
        else:
            error_logger.error("Could not find the film list element on the page")

    except Exception as e:
        error_logger.error(f"Error during link extraction: {e}")
        errors_count += 1

    finally:
        driver.quit()

    df = pd.DataFrame(films_data)

    elapsed_time = time.time() - start_time

    results_logger.info(f"Link extraction completed for year {year}")
    results_logger.info(f"Total movies extracted: {len(films_data)}")
    results_logger.info(f"Errors encountered: {errors_count}")
    results_logger.info(f"Elapsed time: {elapsed_time:.2f} seconds")

    return df


def extract_advanced_data(year, links_df, error_logger, results_logger):
    """Extract detailed movie data from IMDb for a specific year."""
    start_time = time.time()
    results_logger.info(f"Starting advanced data extraction for year {year}")

    all_movie_data = []
    errors_count = 0

    driver = create_edge_driver()

    for url in list(links_df["Movie Link"]):
        try:
            driver.get(url)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.TAG_NAME, "footer")))
            time.sleep(0.05)
            html = driver.page_source
            soup = BeautifulSoup(html, "lxml")
            del html

            budget_text = None
            opening_weekend_text = None
            grossWorldWide_text = None
            gross_US_Canada = None
            release_date_text = None
            list_countries_origin = None
            filmingLocation_texts = None
            productionCompany_text = None
            list_stars = None
            awards_content = None
            writers_text = None
            directors_text = None
            genres_text = []
            languages_list = []

            try:
                budget = soup.find("li", {"data-testid": "title-boxoffice-budget"})
                if budget:
                    budget_text = (
                        budget.find(
                            "span",
                            {"class": "ipc-metadata-list-item__list-content-item"},
                        )
                        .text.replace("\u202f", ",")
                        .replace("\xa0", "")
                    )
            except Exception as e:
                error_logger.error(f"Error extracting budget for {url}: {e}")
                errors_count += 1

            try:
                opening_weekend = soup.find(
                    "li", {"data-testid": "title-boxoffice-openingweekenddomestic"}
                )
                if opening_weekend:
                    opening_weekend_text = (
                        opening_weekend.find_all(
                            "span",
                            {"class": "ipc-metadata-list-item__list-content-item"},
                        )[0]
                        .text.replace("\u202f", ",")
                        .replace("\xa0", "")
                    )
            except Exception as e:
                error_logger.error(f"Error extracting opening weekend for {url}: {e}")
                errors_count += 1

            try:
                gross_worldwide = soup.find(
                    "li", {"data-testid": "title-boxoffice-cumulativeworldwidegross"}
                )
                if gross_worldwide:
                    grossWorldWide_text = (
                        gross_worldwide.find(
                            "span",
                            {"class": "ipc-metadata-list-item__list-content-item"},
                        )
                        .text.replace("\u202f", ",")
                        .replace("\xa0", "")
                    )
            except Exception as e:
                error_logger.error(f"Error extracting worldwide gross for {url}: {e}")
                errors_count += 1

            try:
                gross_US_Canada_section = soup.find(
                    "li", {"data-testid": "title-boxoffice-grossdomestic"}
                )
                if gross_US_Canada_section:
                    gross_US_Canada = (
                        gross_US_Canada_section.find(
                            "span",
                            {"class": "ipc-metadata-list-item__list-content-item"},
                        )
                        .text.replace("\u202f", ",")
                        .replace("\xa0", "")
                    )
            except Exception as e:
                error_logger.error(f"Error extracting US/Canada gross for {url}: {e}")
                errors_count += 1

            try:
                countries_origin = soup.find(
                    "li", {"data-testid": "title-details-origin"}
                )
                if countries_origin:
                    countries_list = countries_origin.find_all(
                        "a", class_="ipc-metadata-list-item__list-content-item"
                    )
                    list_countries_origin = [
                        country.get_text() for country in countries_list
                    ]
                else:
                    list_countries_origin = None
            except Exception as e:
                error_logger.error(
                    f"Error extracting countries of origin for {url}: {e}"
                )
                list_countries_origin = None
                errors_count += 1

            try:
                interests_section = soup.find("div", {"data-testid": "interests"})
                if interests_section:
                    genres = interests_section.find_all("span", class_="ipc-chip__text")
                    genres_text = [genre.get_text() for genre in genres]
            except Exception as e:
                error_logger.error(f"Error extracting genres for {url}: {e}")
                errors_count += 1

            try:
                languages_section = soup.find(
                    "li", {"data-testid": "title-details-languages"}
                )
                if languages_section:
                    languages = languages_section.find_all(
                        "a",
                        class_="ipc-metadata-list-item__list-content-item",
                    )
                    languages_list = [lang.get_text() for lang in languages]
            except Exception as e:
                error_logger.error(f"Error extracting languages for {url}: {e}")
                errors_count += 1

            try:
                awards_div = soup.find("div", {"data-testid": "awards"})
                if awards_div:
                    text = awards_div.find(
                        "a", class_="ipc-metadata-list-item__label"
                    ).get_text()
                    if not text:
                        text = ""
                    else:
                        text += ", "
                    awards_content = (
                        text
                        + awards_div.find(
                            "span", class_="ipc-metadata-list-item__list-content-item"
                        ).get_text()
                    )
            except Exception as e:
                error_logger.error(f"Error extracting awards for {url}: {e}")
                errors_count += 1

            try:
                filming_location_section = soup.find(
                    "li", {"data-testid": "title-details-filminglocations"}
                )
                if filming_location_section:
                    all_filming_locations = filming_location_section.find_all(
                        "li", {"class": "ipc-inline-list__item"}
                    )
                    filmingLocation_texts = [
                        (
                            (
                                filming_location_li.find("a").get_text()
                                + " "
                                + filming_location_li.find("span").get_text()
                            )
                            if filming_location_li.find("a")
                            and filming_location_li.find("span")
                            else filming_location_li.find("a").get_text()
                        )
                        for filming_location_li in all_filming_locations
                    ]
            except Exception as e:
                error_logger.error(f"Error extracting filming locations for {url}: {e}")
                errors_count += 1

            principal_credit = soup.find_all("li", {"class": "ipc-metadata-list__item"})

            try:
                writers_div = principal_credit[1]
                if writers_div:
                    writers_links = writers_div.find_all(
                        "a", {"class": "ipc-metadata-list-item__list-content-item"}
                    )
                    writers_text = [writer.get_text() for writer in writers_links]
            except Exception as e:
                error_logger.error(f"Error extracting writers for {url}: {e}")
                errors_count += 1
            try:
                director_div = principal_credit[0]
                if director_div:
                    directors_links = director_div.find_all(
                        "a", {"class": "ipc-metadata-list-item__list-content-item"}
                    )
                    directors_text = [
                        director.get_text() for director in directors_links
                    ]
            except Exception as e:
                error_logger.error(f"Error extracting director for {url}: {e}")
                errors_count += 1

            # Extract production companies
            try:
                production_companies_section = soup.find(
                    "li", {"data-testid": "title-details-companies"}
                )
                if production_companies_section:
                    companies = production_companies_section.find_all(
                        "a", {"class": "ipc-metadata-list-item__list-content-item"}
                    )
                    productionCompany_text = [company.text for company in companies]
            except Exception as e:
                error_logger.error(
                    f"Error extracting production companies for {url}: {e}"
                )
                errors_count += 1

            try:
                release_date_section = soup.find(
                    "li", {"data-testid": "title-details-releasedate"}
                )
                if release_date_section:
                    release_date_text = release_date_section.find(
                        "a", {"class": "ipc-metadata-list-item__list-content-item"}
                    ).text.split(" (")[0]
            except Exception as e:
                error_logger.error(f"Error extracting release date for {url}: {e}")
                errors_count += 1

            try:
                actors_grid = soup.find(
                    "div",
                    class_="ipc-sub-grid ipc-sub-grid--page-span-2 ipc-sub-grid--wraps-at-above-l ipc-shoveler__grid",
                )
                if actors_grid:
                    actor_divs = actors_grid.find_all(
                        "div", {"data-testid": "title-cast-item"}, limit=10
                    )
                    list_stars = [
                        actor_div.find(
                            "a", {"data-testid": "title-cast-item__actor"}
                        ).get_text()
                        for actor_div in actor_divs
                        if actor_div.find(
                            "a", {"data-testid": "title-cast-item__actor"}
                        )
                    ]
                else:
                    list_stars = None
            except Exception as e:
                error_logger.error(f"Error extracting stars for {url}: {e}")
                list_stars = None
                errors_count += 1

            all_movie_data.append(
                {
                    "link": url,
                    "writers": writers_text,
                    "directors": directors_text,
                    "stars": list_stars,
                    "budget": budget_text,
                    "opening_weekend_Gross": opening_weekend_text,
                    "grossWorldWWide": grossWorldWide_text,
                    "gross_US_Canada": gross_US_Canada,
                    "release_date": release_date_text,
                    "countries_origin": list_countries_origin,
                    "filming_locations": filmingLocation_texts,
                    "production_company": productionCompany_text,
                    "awards_content": awards_content,
                    "genres": genres_text,
                    "Languages": languages_list,
                }
            )

        except Exception as e:
            error_logger.error(f"Error processing URL {url}: {e}")
            errors_count += 1

    driver.quit()

    movies_data = pd.DataFrame(all_movie_data)
    elapsed_time = time.time() - start_time

    results_logger.info(f"Advanced data extraction completed for year {year}")
    results_logger.info(f"Total movies processed: {len(all_movie_data)}")
    results_logger.info(f"Errors encountered: {errors_count}")
    results_logger.info(f"Elapsed time: {elapsed_time:.2f} seconds")

    return movies_data


def merge_data(year, data_dir, error_logger, results_logger):
    """Merge basic and advanced movie data for a specific year."""
    start_time = time.time()
    results_logger.info(f"Starting data merging for year {year}")

    try:

        advanced_file = f"{data_dir}/advanced_movies_details_{year}.csv"
        basic_file = f"{data_dir}/imdb_movies_{year}.csv"

        movies_data = pd.read_csv(advanced_file)
        df = pd.read_csv(basic_file)

        movies_data.rename(columns={"link": "Movie Link"}, inplace=True)

        merged_data = pd.merge(df, movies_data, how="inner", on="Movie Link")
        elapsed_time = time.time() - start_time

        results_logger.info(f"Basic data rows: {len(df)}")
        results_logger.info(f"Advanced data rows: {len(movies_data)}")
        results_logger.info(f"Merged data rows: {len(merged_data)}")
        results_logger.info(f"Data merging completed in {elapsed_time:.2f} seconds")

        return merged_data

    except Exception as e:
        error_logger.error(f"Error merging data for year {year}: {e}")
        results_logger.info(f"Data merging failed for year {year}")
        return None


def process_year(year, max_movies=600):
    """Scrape, enrich, merge, and save IMDb movie data for one year."""
    print(f"Starting processing for year {year}")
    start_time = time.time()

    data_dir, logs_dir = setup_directories(year)
    error_logger, results_logger = setup_logging(year)

    try:
        results_logger.info(
            f"===== Starting IMDB data processing for year {year} ====="
        )
        results_logger.info(
            f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(f"Extracting basic movie information for {year}...")
        links_df = extract_links(year, error_logger, results_logger, max_movies)
        basic_file = f"{data_dir}/imdb_movies_{year}.csv"
        links_df.to_csv(basic_file, index=False)
        results_logger.info(f"Saved basic movie information to {basic_file}")
        print(f"Basic movie information saved to {basic_file}")

        print(f"Extracting advanced movie details for {year}...")
        advanced_df = extract_advanced_data(
            year, links_df, error_logger, results_logger
        )
        advanced_file = f"{data_dir}/advanced_movies_details_{year}.csv"
        advanced_df.to_csv(advanced_file, index=False)
        results_logger.info(f"Saved advanced movie details to {advanced_file}")
        print(f"Advanced movie details saved to {advanced_file}")

        print(f"Merging movie data for {year}...")
        merged_df = merge_data(year, data_dir, error_logger, results_logger)

        if merged_df is not None:
            merged_file = f"{data_dir}/merged_movies_data_{year}.csv"
            merged_df.to_csv(merged_file, index=False)
            results_logger.info(f"Saved merged movie data to {merged_file}")
            print(f"Merged movie data saved to {merged_file}")
        else:
            print(f"Error: Failed to merge data for {year}")

        total_elapsed_time = time.time() - start_time
        results_logger.info(
            f"Total processing time for year {year}: {total_elapsed_time:.2f} seconds"
        )
        results_logger.info(
            f"===== Completed IMDB data processing for year {year} ====="
        )

        print(
            f"Processing completed for year {year}. Total time: {total_elapsed_time:.2f} seconds"
        )

    except Exception as e:
        error_logger.error(f"Critical error during processing for year {year}: {e}")
        results_logger.info(f"Processing failed for year {year}")
        print(f"Error: Processing failed for year {year}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Scrape IMDb movie data by year.")
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--max-movies", type=int, default=600)
    args = parser.parse_args()

    for year in range(args.start_year, args.end_year + 1):
        print(f"\n{'='*50}\nProcessing year {year}\n{'='*50}")
        process_year(year, args.max_movies)

        # avoid potential rate limiting
        if year < args.end_year:
            print("Waiting 8 seconds before processing the next year...")
            time.sleep(8)

    print("\nAll years processed successfully!")


if __name__ == "__main__":
    main()
