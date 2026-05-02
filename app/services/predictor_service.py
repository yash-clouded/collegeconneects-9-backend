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
        ].copy()

        if filtered.empty:
            return []

        # Find colleges where user_rank <= ClosingRank (eligible colleges)
        eligible = filtered[filtered['ClosingRank'] >= user_rank].copy()
        
        if eligible.empty:
            return []
            
        # Detect Institute Type
        def get_type(name):
            name_upper = name.upper()
            if "INDIAN INSTITUTE OF TECHNOLOGY" in name_upper:
                return "IIT"
            if "NATIONAL INSTITUTE OF TECHNOLOGY" in name_upper or ", NIT" in name_upper or " NIT " in name_upper or name_upper.startswith("NIT "):
                return "NIT"
            if "INDIAN INSTITUTE OF INFORMATION TECHNOLOGY" in name_upper or "IIIT" in name_upper:
                return "IIIT"
            return "Other"

        eligible['Type'] = eligible['Institute'].apply(get_type)

        # Categorize results
        # Dream: Closing rank is within 20% of user rank (Close to missing)
        # Safe: Closing rank is > 20% above user rank
        eligible['Status'] = eligible['ClosingRank'].apply(
            lambda x: "Dream" if x < user_rank * 1.2 else "Safe"
        )

        # Sort: Dream first (alphabetically D < S), then by ClosingRank
        eligible = eligible.sort_values(by=['Status', 'ClosingRank'], ascending=[True, True])
        
        # Return up to 50 results
        results = eligible.head(50).to_dict(orient='records')
        return results

    def get_all_colleges(self):
        if self.df is None:
            return []
        return self.df.to_dict(orient='records')

# Singleton instance
csv_file = os.path.join(os.path.dirname(__file__), "..", "data", "college_cutoffs.csv")
predictor = CollegePredictor(csv_file)
