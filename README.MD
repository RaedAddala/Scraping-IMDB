# IMDB Movie Data Scraper

This Python script extracts comprehensive movie data from IMDB, focusing on top-grossing movies from 1960 to 2024. The scraper collects detailed information including box office performance, cast & crew, awards, and other key metrics.

## Data Collection

For each year, the script collects:

- Basic movie information (title, year, duration, MPA rating, IMDb rating, votes).
- Financial data (budget, worldwide gross, US/Canada gross, opening weekend).
- Credits (directors, writers, stars).
- Additional details (genres, countries, filming locations, production companies, languages).
- Awards information (wins, nominations, Oscars).
- Release date information.

## Requirements

```python
python 3
Jupyter
selenium
beautifulsoup4
pandas
```

## Setup

1. Install the required packages:

    ```bash
    pip install selenium beautifulsoup4 pandas
    ```

2. Download a WebDriver:
   - The script uses Microsoft Edge WebDriver by default.
   - Can be modified to use Chrome, Firefox, or other WebDrivers.
   - Place the driver executable in the project directory.

## Usage

1. The script will create a `Data` directory organized by year
2. For each year, it generates three CSV files:
   - `imdb_movies_[year].csv`: Basic movie information
   - `advanced_movies_details_[year].csv`: Detailed movie data
   - `merged_movies_data_[year].csv`: Combined dataset

```python
# Run for a specific year
crawl_imdb_movies(2023)

# Run for multiple years
years_to_crawl = range(1960, 2024)
for year in years_to_crawl:
    crawl_imdb_movies(year)
```

## Data Usage

The collected data is available under the MIT License. You are free to:

- Use the data commercially.
- Modify and distribute the data.
- Sublicense and sell the data.
- Use the data for private use.

## Notes

- Respects IMDB's robots.txt and implements appropriate delays between requests.
- Some movies may have incomplete data if information is not available on IMDB.
- Box office data availability may vary, especially for older movies.

## Data Structure

### imdb_movies_[year].csv

- Title: Movie title
- Movie Link: IMDB URL
- Year: Release year
- Duration: Movie length
- MPA: Rating (PG, R, etc.)
- Rating: IMDB rating
- Votes: Number of user votes

### advanced_movies_details_[year].csv

- Movie Link: IMDB URL
- budget: Production budget
- grossWorldWide: Global box office
- gross_US_Canada: North American box office
- opening_weekend_Gross: Opening weekend earnings
- directors: Director list
- writers: Writer list
- stars: Main cast
- genres: Movie genres
- countries_origin: Production countries
- filming_locations: Shooting locations
- production_companies: Production companies
- Languages: Available languages
- wins: Award wins
- nominations: Award nominations
- oscars: Oscar nominations
- release_date: Release date

## Troubleshooting

1. WebDriver Issues:

    ```python
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    ```

2. Rate Limiting:

- Adjust `time.sleep()` values if encountering blocks.
- Use proxy rotation if needed.

## Error Handling

The script includes robust error handling:

- Continues processing if individual movie fails.
- Saves partial data if session interrupts.
- Logs errors for debugging.

## Memory Usage

For large date ranges:

- Process years in batches.
- Clear DataFrame objects regularly.
- Monitor memory consumption.

## Contributing

1. Fork the repository.
2. Create feature branch.
3. Submit pull request.

## Contact

For issues or data requests:

- Open GitHub issue.
- Submit issue or data requests or suggestions for better code readability, robustness and performance.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
