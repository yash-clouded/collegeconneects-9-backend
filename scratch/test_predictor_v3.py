import os
import sys

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.predictor_service import CollegePredictor

def test_prediction():
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "data", "college_cutoffs.csv"))
    print(f"Testing with CSV: {csv_path}")
    
    predictor = CollegePredictor(csv_path)
    
    # Test case from user: Rank 200, Category SC, Gender Gender-Neutral
    print("\nTesting User Case: Rank 200, SC, Gender-Neutral")
    results = predictor.predict(200, "SC", "Gender-Neutral")
    print(f"Results found: {len(results)}")
    for i, r in enumerate(results[:5]):
        print(f"{i+1}. {r['Institute']} - {r['Program']} (Rank: {r['ClosingRank']})")

    # Test case: Open category, Rank 15000
    print("\nTesting Case: Rank 15000, OPEN, Gender-Neutral")
    results = predictor.predict(15000, "OPEN", "Gender-Neutral")
    print(f"Results found: {len(results)}")
    for i, r in enumerate(results[:10]):
        print(f"{i+1}. [{r['Type']}] {r['Institute']} - {r['Program']} (Rank: {r['ClosingRank']}, Status: {r['Status']})")

if __name__ == "__main__":
    test_prediction()
