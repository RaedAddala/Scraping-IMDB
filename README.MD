# IMDB Movie Data Scraper

This Python project extracts comprehensive movie data from IMDb, focusing on the **top-grossing movies** from **1960 to 2024**. It collects detailed information, including box office performance, cast & crew, awards, and other key metrics, organizing the data in a structured format for analysis.  

I uploaded the [Dataset](https://www.kaggle.com/datasets/raedaddala/imdb-movies-from-1960-to-2023) to Kaggle. Check it out.

Here is the Merged Dataset alongside several notebooks related to its study: Check this [Kaggle link](https://www.kaggle.com/datasets/raedaddala/top-500-600-movies-of-each-year-from-1960-to-2024)

## Features

### Data Collection

The scraper collects the following details for each year:  

- **Basic Information**: Title, year, duration, MPA rating, IMDb rating, and user votes.  
- **Financial Data**: Budget, worldwide gross, US/Canada gross, and opening weekend revenue.  
- **Credits**: Directors, writers, and main cast.  
- **Additional Details**: Genres, production countries, filming locations, production companies, and available languages.  
- **Awards**: Wins, nominations, and Oscar statistics.  
- **Release Information**: Official release dates.  

### Output Structure

For each year, the script generates:  

1. **`imdb_movies_[year].csv`**: Contains basic movie information.  
2. **`advanced_movies_details_[year].csv`**: Contains detailed movie data.  
3. **`merged_movies_data_[year].csv`**: Combines data from the other two files for a complete dataset.  

### Consistent Data Structure

All files follow a consistent template across years, enabling seamless analysis. Below are the templates for each file:  

- **`imdb_movies_[year].csv`**:  
  `Title, Movie Link, Year, Duration, MPA, Rating, Votes`  

- **`advanced_movies_details_[year].csv`**:  
  `Movie Link, budget, grossWorldWide, gross_US_Canada, opening_weekend_Gross, directors, writers, stars, genres, countries_origin, filming_locations, production_companies, Languages, wins, nominations, oscars, release_date`  

- **`merged_movies_data_[year].csv`**:  
  `Title, Movie Link, Year, Duration, MPA, Rating, Votes, budget, grossWorldWide, gross_US_Canada, opening_weekend_Gross, directors, writers, stars, genres, countries_origin, filming_locations, production_companies, Languages, wins, nominations, oscars, release_date`  

### Updates

The dataset is updated annually every **December** to include the most recent data.

## Requirements

Ensure you have the following installed:  

```bash
python 3
Jupyter
selenium
beautifulsoup4
pandas
```

## Setup

1. Install the required Python packages:

    ```bash
    pip install selenium beautifulsoup4 pandas
    ```

2. Download a WebDriver:
   - The script uses **Microsoft Edge WebDriver** by default.
   - Modify the code to use Chrome, Firefox, or another WebDriver if preferred.
   - Place the WebDriver executable in the project directory or add it to your PATH.

## Usage

### Run the Scraper  

The scraper organizes the output into a `Data` directory, structured by year. For each year, it generates 3 CSV files:

- `imdb_movies_[year].csv`: Basic movie information
- `advanced_movies_details_[year].csv`: Detailed movie data
- `merged_movies_data_[year].csv`: Combined dataset

Use the following commands to run the scraper:

```python
# Run for a specific year
crawl_imdb_movies(2023)

# Run for multiple years
years_to_crawl = range(1960, 2024)
for year in years_to_crawl:
    crawl_imdb_movies(year)
```

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

### `advanced_movies_details_[year].csv`

Provides detailed movie data, including:

- **Movie Link**: IMDb URL for the movie.  
- **budget**: Production budget (in USD).  
- **grossWorldWide**: Total global box office earnings.  
- **gross_US_Canada**: North American box office earnings.  
- **opening_weekend_Gross**: Opening weekend revenue.  
- **directors**: List of directors.  
- **writers**: List of writers.  
- **stars**: Main cast members.  
- **genres**: Movie genres.  
- **countries_origin**: Countries of production.  
- **filming_locations**: Primary shooting locations.  
- **production_companies**: Associated production companies.  
- **Languages**: Available languages for the movie.  
- **wins**: Number of award wins.  
- **nominations**: Number of award nominations.  
- **Oscars**: Number of Oscar nominations.  
- **release_date**: Official release date.  

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
