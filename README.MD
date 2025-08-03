# IMDB Movie Data Scraper

This Python project scrapes comprehensive movie data from *IMDb*, focusing on the **top-grossing movies** across an expanded range of years: **1920 to 2025**. It extracts detailed information, including *box office performance*, *cast & crew*, *awards*, and other key metrics, organizing the data in a structured format for analysis.  

I uploaded the [Dataset](https://www.kaggle.com/datasets/raedaddala/imdb-movies-from-1960-to-2023) to Kaggle.

Here is the Merged Dataset alongside several notebooks related to its study: Check this [Kaggle link](https://www.kaggle.com/datasets/raedaddala/top-500-600-movies-of-each-year-from-1960-to-2024)

## Table Of Content

- [IMDB Movie Data Scraper](#imdb-movie-data-scraper)
- [Dataset](#dataset)
- [Features](#features)
  - [Data Collection](#data-collection)
  - [Output Structure](#output-structure)
  - [Consistent Data Structure](#consistent-data-structure)
  - [Updates](#updates)
- [Requirements](#requirements)
- [Setup](#setup)
- [Usage](#usage)
  - [Run the Scraper](#run-the-scraper)
  - [Logging](#logging)
- [Data Structure and Files](#data-structure-and-files)
  - [`imdb_movies_[year].csv`](#imdb_movies_yearcsv)
  - [`advanced_movies_details_[year].csv`](#advanced_movies_details_yearcsv)
  - [`merged_movies_data_[year].csv`](#merged_movies_data_yearcsv)
- [Applications](#applications)
- [Troubleshooting](#troubleshooting)
  - [Common Issues](#common-issues)
  - [Memory Management](#memory-management)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Dataset

Check [the notebook](./Dataset/guide-to-extracting-data-from-this-dataset.ipynb) that generated the [dataset](./Dataset/cleaned_data_from_1920_to_2025.csv).

For futher data cleaning and normalization, check this [notebook](./Dataset/cleaning-and-normalizing-data.ipynb).

## Features

### Data Collection

The scraper collects the following details for each year:  

- **Basic Information**: Title, year, duration, MPA rating, IMDb rating, user votes, meta score, and description.
- **Financial Data**: Budget, worldwide gross, US/Canada gross, and opening weekend revenue.  
- **Credits**: Directors, writers, and main cast (stars/actors).  
- **Additional Details**: Genres, production countries, filming locations, production companies, languages, and release dates.  
- **Awards**: Wins, nominations, Oscars, and detailed awards content.  

### Output Structure

For each year, the script generates:  

1. **`imdb_movies_[year].csv`**: Contains basic movie information.  
2. **`advanced_movies_details_[year].csv`**: Contains detailed movie metadata.  
3. **`merged_movies_data_[year].csv`**: Combines data from the other two files for a complete dataset.  

### Consistent Data Structure

All files follow a consistent template across years, enabling seamless analysis. Below are the templates for each file:  

- **`imdb_movies_[year].csv`**:  
  `Title, Year, Duration, MPA, Rating, Votes, meta_score, description, Movie Link`  

- **`advanced_movies_details_[year].csv`**:  
  `link, writers, directors, stars, budget, opening_weekend_Gross, grossWorldWide, gross_US_Canada, release_date, countries_origin, filming_locations, production_company, awards_content, genres, Languages`  

- **`merged_movies_data_[year].csv`**:  
  `Title, Year, Duration, MPA, Rating, Votes, meta_score, description, Movie Link, writers, directors, stars, budget, opening_weekend_Gross, grossWorldWide, gross_US_Canada, release_date, countries_origin, filming_locations, production_company, awards_content, genres, Languages`  

### Updates

The dataset is updated annually every **December** to include the latest data, with historical data now extending back to 1920.

## Requirements

- This is Cross platform and browser agnostic, you can use any modern web browser (e.g., Edge, Chrome, Firefox) with a matching WebDriver.
- Ensure you have the following installed:

   ```bash
   python 3
   Jupyter
   selenium
   beautifulsoup4
   pandas
   lxml
   ```

- Stable Internet Connection.

## Setup

1. Install the required Python packages:

    ```bash
    pip install selenium beautifulsoup4 pandas lxml
    ```

2. Download a WebDriver:
   - The script uses **Microsoft Edge WebDriver** by default.
   - Modify the code to use Chrome, Firefox, or another WebDriver if preferred.
   - Place the WebDriver executable in the project directory or add it to your PATH.

## Usage

### Run the Scraper  

The scraper organizes the output into a `Data/[year]` directory structure. For each year, it generates 3 CSV files:

- `imdb_movies_[year].csv`: Basic movie information
- `advanced_movies_details_[year].csv`: Detailed movie data
- `merged_movies_data_[year].csv`: Combined dataset

Use the following commands to run the scraper:

```python
# Run for a specific year
process_year(2023)

# Run for multiple years
years_to_crawl = range(1920, 2025)
for year in years_to_crawl:
    process_year(year)
```

### Logging

- Separate log files are created for each year in `Logs/[year]`.  
- Logs track errors, processing results, and runtime statistics.
- For each year there are **2 log files**:
  - errors
  - results

---

## Data Structure and Files  

### `imdb_movies_[year].csv`  

Contains essential movie information, including:  

- **Title**: Movie title.  
- **Movie Link**: IMDb URL for the movie.  
- **Year**: Year of release.  
- **Duration**: Movie runtime (in minutes).  
- **MPA**: Motion Picture Association rating (e.g., PG, R).  
- **Rating**: IMDb rating (on a scale of 1–10).  
- **Votes**: Number of user votes on IMDb.
- **meta_score**: MetaCritic score (if available).  
- **description**: Brief movie synopsis.  

### `advanced_movies_details_[year].csv`

Provides detailed movie data, including:

- **link**: IMDb URL.  
- **writers**: List of writers.  
- **directors**: List of directors.  
- **stars**: Main cast members.  
- **budget**: Production budget (USD).  
- **opening_weekend_Gross**: Opening weekend earnings.  
- **grossWorldWide**: Global box office earnings.  
- **gross_US_Canada**: North American earnings.  
- **release_date**: Official release date.  
- **countries_origin**: Production countries.  
- **filming_locations**: Primary shooting locations.  
- **production_company**: Associated companies.  
- **awards_content**: Detailed awards data (wins/nominations).  
- **genres**: Movie genres.  
- **Languages**: Available languages.

### `merged_movies_data_[year].csv`  

Combines all columns from `imdb_movies_[year].csv` and `advanced_movies_details_[year].csv` for a unified dataset.  

---

## Applications  

This dataset is ideal for:  

- **Analyzing trends** in the movie industry over time.  
- Building **predictive models** for box office performance or awards.  
- Developing **recommendation systems** based on movie attributes.  

---

## Troubleshooting  

### Common Issues  

1. **WebDriver Errors**:  
   Adjust browser options:  

   ```python
   options = Options()
   options.add_argument("--disable-gpu")
   options.add_argument("--no-sandbox")
   ```  

2. **Rate Limiting**:  
   - Increase `time.sleep()` delays between requests.  
   - Use proxy rotation for high-volume scraping.  

3. **Incomplete Data**:  
   - Some older movies may lack detailed financial or award information.  

### Memory Management  

For large date ranges:  

- Process data in smaller batches.  
- Clear DataFrame objects regularly using `del` and `gc.collect()`.  

---

## Contributing  

We welcome contributions to improve the scraper or extend its functionality!  

1. **Fork** this repository.  
2. Create a feature branch:  

   ```bash
   git checkout -b feature-name
   ```  

3. Commit changes:  

   ```bash
   git commit -m "Add feature"  
   ```  

4. Submit a **pull request**.  

---

## License  

This project is licensed under the **MIT License**. See the `LICENSE` file for details.  

---

## Contact  

For issues, suggestions, or feature requests:  

- Open an issue on GitHub.  
- Reach out with ideas to improve code readability, robustness, and performance.
