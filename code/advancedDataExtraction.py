from selenium import webdriver
from bs4 import BeautifulSoup
from selenium.webdriver.edge.service import Service
import pandas as pd

all_movie_data = []
df = pd.read_csv(f"imdb_movies1978_1980.csv")

driver_path = "Edgedriver.exe"
options = webdriver.EdgeOptions()
options.add_argument("--lang=en-US")

service = Service(executable_path=driver_path)
driver = webdriver.Edge(service=service, options=options)

for url in list(df["Movie Link"]):
    driver.get(url)
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    budget_text = None
    opening_weekend_text = None
    grossWorldWide_text = None
    gross_US_Canada = None
    release_date_text = None
    countries_origin_text = None
    filmingLocation_text = None
    productionCompany_text = None
    director_text = None
    stars_text = None
    awards_content = None
    writers_text = None
    genres_text = []
    languages_list = []

    try:
        budget = soup.find("li", {"data-testid": "title-boxoffice-budget"})
        if budget:
            budget_text = (
                budget.find(
                    "span", {"class": "ipc-metadata-list-item__list-content-item"}
                )
                .text.replace("\u202f", ",")
                .replace("\xa0", "")
            )
    except Exception:
        pass

    try:
        opening_weekend = soup.find(
            "li", {"data-testid": "title-boxoffice-openingweekenddomestic"}
        )
        if opening_weekend:
            opening_weekend_text = (
                opening_weekend.find_all(
                    "span", {"class": "ipc-metadata-list-item__list-content-item"}
                )[0]
                .text.replace("\u202f", ",")
                .replace("\xa0", "")
            )
    except Exception:
        pass

    try:
        gross_worldwide = soup.find(
            "li", {"data-testid": "title-boxoffice-cumulativeworldwidegross"}
        )
        if gross_worldwide:
            grossWorldWide_text = (
                gross_worldwide.find(
                    "span", {"class": "ipc-metadata-list-item__list-content-item"}
                )
                .text.replace("\u202f", ",")
                .replace("\xa0", "")
            )
    except Exception:
        pass

    try:
        gross_US_Canada_section = soup.find(
            "li", {"data-testid": "title-boxoffice-grossdomestic"}
        )
        if gross_US_Canada_section:
            gross_US_Canada = (
                gross_US_Canada_section.find(
                    "span", {"class": "ipc-metadata-list-item__list-content-item"}
                )
                .text.replace("\u202f", ",")
                .replace("\xa0", "")
            )
    except Exception:
        pass

    try:
        countries_origin = soup.find("li", {"data-testid": "title-details-origin"})
        if countries_origin:
            countries_list = countries_origin.find_all(
                "a", class_="ipc-metadata-list-item__list-content-item"
            )
            list_countries_origin = [country.get_text() for country in countries_list]
        else:
            list_countries_origin = None
    except Exception:
        list_countries_origin = None

    try:
        interests_section = soup.find("div", {"data-testid": "interests"})
        if interests_section:
            genres = interests_section.find_all("span", class_="ipc-chip__text")
            genres_text = [genre.get_text() for genre in genres]
    except Exception:
        pass

    try:
        languages_section = soup.find("li", {"data-testid": "title-details-languages"})
        if languages_section:
            languages = languages_section.find_all(
                "a",
                class_="ipc-metadata-list-item__list-content-item "
                "ipc-metadata-list-item__list-content-item--link",
            )
            languages_list = [lang.get_text() for lang in languages]
    except Exception:
        pass

    try:
        director_section = soup.find("li", {"class": "ipc-metadata-list__item"})
        if director_section:
            director_text = director_section.find(
                "a", {"class": "ipc-metadata-list-item__list-content-item"}
            ).text
    except Exception:
        pass

    try:
        awards_div = soup.find("div", {"data-testid": "awards"})
        if awards_div:
            awards_content = awards_div.find(
                "span", class_="ipc-metadata-list-item__list-content-item"
            ).get_text()
    except Exception:
        pass

    try:
        filming_location_section = soup.find(
            "li", {"data-testid": "title-details-filminglocations"}
        )
        if filming_location_section:
            filmingLocation_text = filming_location_section.find(
                "a", {"class": "ipc-metadata-list-item__list-content" "-item"}
            ).text
    except Exception:
        pass

    try:
        writers_div = soup.find(
            "li",
            {
                "role": "presentation",
                "class": "ipc-metadata-list__item " "ipc-metadata-list-item--link",
            },
        )
        if writers_div:
            writers_links = writers_div.find_all(
                "a",
                class_="ipc-metadata-list-item__list-content-item "
                "ipc-metadata-list-item__list-content-item--link",
            )
            writers_text = [writer.get_text() for writer in writers_links]
    except Exception:
        pass

    try:
        production_companies_section = soup.find(
            "li", {"data-testid": "title-details-companies"}
        )
        if production_companies_section:
            companies = production_companies_section.find_all(
                "a", {"class": "ipc-metadata-list-item__list-content-item"}
            )
            productionCompany_text = [company.text for company in companies]
    except Exception:
        pass

    try:
        release_date_section = soup.find(
            "li", {"data-testid": "title-details-releasedate"}
        )
        if release_date_section:
            release_date_text = release_date_section.find(
                "a", {"class": "ipc-metadata-list-item__list-content-item"}
            ).text.split(" (")[0]
    except Exception:
        pass

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
                if actor_div.find("a", {"data-testid": "title-cast-item__actor"})
            ]
        else:
            list_stars = None
    except Exception:
        list_stars = None

    all_movie_data.append(
        {
            "link": url,
            "writers": writers_text,
            "director": director_text,
            "stars": list_stars,
            "budget": budget_text,
            "opening_weekend_Gross": opening_weekend_text,
            "grossWorldWWide": grossWorldWide_text,
            "gross_US_Canada": gross_US_Canada,
            "release_date": release_date_text,
            "countries_origin": list_countries_origin,
            "filming_locations": filmingLocation_text,
            "production_company": productionCompany_text,
            "awards_content": awards_content,
            "genres": genres_text,
            "Languages": languages_list,
        }
    )

movies_data = pd.DataFrame(all_movie_data)
movies_data.to_csv("advanced_movies_details1978_1980.csv", index=False)
