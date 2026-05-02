from app.services.predictor_service import predictor

def test_prediction():
    print("Testing rank 1500...")
    res = predictor.predict(1500)
    for r in res:
        print(f" - {r['Institute']}: {r['Program']} ({r['ClosingRank']})")

    print("\nTesting rank 25000...")
    res = predictor.predict(25000)
    for r in res:
        print(f" - {r['Institute']}: {r['Program']} ({r['ClosingRank']})")

    print("\nTesting rank 100000 (Should be empty)...")
    res = predictor.predict(100000)
    print(f" Results: {res}")

if __name__ == "__main__":
    test_prediction()
