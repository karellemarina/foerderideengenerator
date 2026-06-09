import pandas as pd

EXCEL_PATH = "BEOKIZ_Wissensbasis_v7_komplett_mit_Medien_LoRA.xlsx"
SHEET_NAME = "Wissensbasis"  # nom de l'onglet dans le fichier

def main():
    print("Je tente de lire le fichier Excel...")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)
    print("Lecture OK !")
    print("Colonnes :", df.columns.tolist())
    print("Premières lignes :")
    print(df.head())

if __name__ == "__main__":
    main()
