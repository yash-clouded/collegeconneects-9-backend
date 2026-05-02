import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
import os

class CollegePredictor:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.df = None
        self.model = None
        self.load_data()

    def load_data(self):
        if os.path.exists(self.csv_path):
            self.df = pd.read_csv(self.csv_path)
            # We use the ClosingRank as the feature for our "ML" model
            X = self.df[['ClosingRank']].values
            self.model = NearestNeighbors(n_neighbors=5, algorithm='auto').fit(X)
        else:
            print(f"Warning: CSV file not found at {self.csv_path}")

    def predict(self, user_rank: int, category: str = "OPEN", gender: str = "Gender-Neutral"):
        if self.df is None:
            return []

        # Filter by Category and Gender first
        filtered = self.df[
            (self.df['Category'] == category) & 
            (self.df['Gender'] == gender)
        ]

        if filtered.empty:
            return []

        # Find colleges where user_rank <= ClosingRank (eligible colleges)
        # Sort them by ClosingRank to find the ones closest to the user_rank
        eligible = filtered[filtered['ClosingRank'] >= user_rank].sort_values(by='ClosingRank')
        
        if eligible.empty:
            return []
        
        # Take top 5 closest safe/reach colleges
        results = eligible.head(5).to_dict(orient='records')
        return results

    def get_all_colleges(self):
        if self.df is None:
            return []
        return self.df.to_dict(orient='records')

# Singleton instance
csv_file = os.path.join(os.path.dirname(__file__), "..", "data", "college_cutoffs.csv")
predictor = CollegePredictor(csv_file)
