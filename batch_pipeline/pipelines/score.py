"""Evaluation script for measuring mean squared error."""
import logging
import pathlib
import glob
import pickle
import tarfile
from math import sqrt

import pandas as pd
import xgboost

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())


def load_data(file_list: list):
    # Load input files with header
    dfs = []
    for file in file_list:
        dfs.append(pd.read_csv(file))
    return pd.concat(dfs, ignore_index=True)


if __name__ == "__main__":
    logger.debug("Starting evaluation.")
    model_path = "/opt/ml/processing/model/model.tar.gz"
    with tarfile.open(model_path) as tar:
        
        import os
        
        def is_within_directory(directory, target):
            
            abs_directory = os.path.abspath(directory)
            abs_target = os.path.abspath(target)
        
            prefix = os.path.commonprefix([abs_directory, abs_target])
            
            return prefix == abs_directory
        
        def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
        
            for member in tar.getmembers():
                member_path = os.path.join(path, member.name)
                if not is_within_directory(path, member_path):
                    raise Exception("Attempted Path Traversal in Tar File")
        
            tar.extractall(path, members, numeric_owner=numeric_owner) 
            
        
        safe_extract(tar, path=".")

    logger.debug("Loading xgboost model.")
    model = pickle.load(open("xgboost-model", "rb"))

    logger.debug("Reading input data.")

    # Get input file list
    input_file_list = glob.glob("/opt/ml/processing/input/*.csv")

    # Drop the first target column
    df = load_data(input_file_list)
    target_col = "fare_amount"
    X_test = xgboost.DMatrix(df.drop(target_col, axis=1).values)

    logger.info("Performing predictions against test data.")
    predictions = model.predict(X_test)

    # Replace the target column with predictions, to allow comparing in model monitor
    df[target_col] = predictions

    output_dir = "/opt/ml/processing/output"
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Writing out scores with header")
    df.to_csv(f"{output_dir}/scores.csv", index=False, header=True)
