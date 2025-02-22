import pandas as pd


def merge_data(d1, d2, output):
    movies_data = pd.read_csv(d1)
    df = pd.read_csv(d2)
    movies_data.rename(columns={"link": "Movie Link"}, inplace=True)
    merged_data = pd.merge(df, movies_data, how="inner", on="Movie Link")
    merged_data.to_csv(output, index=False)


def merge_years(file_list, output):
    dataframes = []
    for file in file_list:
        try:
            df = pd.read_csv(file)
            dataframes.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")
    combined_df = pd.concat(dataframes, ignore_index=True)
    combined_df.to_csv(output, index=False)


if __name__ == "__main__":
    merge_data(
        "advanced_movies_details1978_1980.csv",
        "imdb_movies1978_1980.csv",
        "merged_movies_data1978_1980.csv",
    )
