"""Evaluation script for measuring mean squared error."""
import logging
import pathlib
import glob
import os
import pickle
import tarfile

import pandas as pd
import xgboost

from math import sqrt

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())


def load_data(file_list: list):
    # Header columns
    cols = [
        "fare_amount",
        "passenger_count",
        "pickup_latitude",
        "pickup_longitude",
        "dropoff_latitude",
        "dropoff_longitude",
        "geo_distance",
        "hour",
        "weekday",
        "month",
    ]
    # Concat input files with select columns
    dfs = []
    for file in file_list:
        dfs.append(pd.read_csv(file, names=cols, index_col=None))
    return pd.concat(dfs, ignore_index=True)


if __name__ == "__main__":
    logger.debug("Starting evaluation.")
    model_path = "/opt/ml/processing/model/model.tar.gz"
    with tarfile.open(model_path) as tar:
        tar.extractall(path=".")

    logger.debug("Loading xgboost model.")
    model = pickle.load(open("xgboost-model", "rb"))

    logger.debug("Reading input data.")

    # Get input file list
    input_file_list = glob.glob("/opt/ml/processing/input/*.csv")

    # Drop the first target column
    df = load_data(input_file_list)
    X_test = xgboost.DMatrix(df.drop("fare_amount", axis=1).values)

    logger.info("Performing predictions against test data.")
    predictions = model.predict(X_test)
    df["fare_amount_prediction"] = predictions

    output_dir = "/opt/ml/processing/output"
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Writing out scores with header")
    df.to_csv(f"{output_dir}/scores.csv", index=False, header=True)
