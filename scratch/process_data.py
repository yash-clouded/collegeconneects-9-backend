import csv
import sys

def transform_data(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'a', encoding='utf-8', newline='') as f_out:
        
        reader = csv.DictReader(f_in)
        writer = csv.writer(f_out)
        
        # Mapping:
        # Institute -> Institute
        # Academic Program Name -> Program
        # Seat Type -> Category
        # Gender -> Gender
        # Closing Rank -> ClosingRank
        
        for row in reader:
            writer.writerow([
                row['Institute'],
                row['Academic Program Name'],
                row['Seat Type'],
                row['Gender'],
                row['Closing Rank']
            ])

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python process_data.py input.csv output.csv")
    else:
        transform_data(sys.argv[1], sys.argv[2])
