import pandas as pd
import requests
import io
import xlsxwriter

# --- Configuration ---
INPUT_FILE = 'pokemon_data.csv'  # Your new file
OUTPUT_FILE = 'Pokemon_Sprites_Clean.xlsx'  # The result file


# ---------------------

def get_api_name(display_name):
    """
    Converts display names to PokeAPI format.
    Examples:
      "Mega Mewtwo Y" -> "mewtwo-mega-y"
      "Galarian Darmanitan" -> "darmanitan-galar"
      "Shaymin-Sky" -> "shaymin-sky"
    """
    name = str(display_name).lower().strip()

    # 1. Replace special chars and spaces
    name = name.replace('.', '').replace("'", '').replace(':', '').replace(' ', '-')

    # 2. Handle Regional Prefixes (move to end)
    prefixes = {
        'alolan-': '-alola',
        'galarian-': '-galar',
        'hisuian-': '-hisui',
        'paldean-': '-paldea'
    }
    for prefix, suffix in prefixes.items():
        if name.startswith(prefix):
            name = name.replace(prefix, '') + suffix
            return name  # Usually regional forms don't have other suffixes

    # 3. Handle Mega Evolutions (move 'mega' to the correct spot)
    if name.startswith('mega-'):
        parts = name.split('-')
        # Case: Mega-Mewtwo-Y -> mewtwo-mega-y
        if len(parts) == 3:
            return f"{parts[1]}-mega-{parts[2]}"
        # Case: Mega-Venusaur -> venusaur-mega
        elif len(parts) == 2:
            return f"{parts[1]}-mega"

    # 4. Handle Gigantamax
    if name.endswith('-gigantamax') or name.endswith('-gmax'):
        return name.replace('-gigantamax', '-gmax')

    # 5. Manual Overrides for tricky ones
    overrides = {
        'nidoran-f': 'nidoran-f',
        'nidoran-m': 'nidoran-m',
        'mime-jr': 'mime-jr',
        'mr-mime': 'mr-mime',
        'type:-null': 'type-null',
        'farfetchd': 'farfetchd',
        'flabebe': 'flabebe',
        'zygarde-10%': 'zygarde-10',  # PokeAPI uses 'zygarde-10' or 'zygarde-10-power-construct'
        'zygarde-complete': 'zygarde-complete',
    }

    return overrides.get(name, name)


def main():
    print(f"Reading {INPUT_FILE}...")
    try:
        df = pd.read_csv(INPUT_FILE)
    except FileNotFoundError:
        print("Error: Input file not found!")
        return

    # Add the Cleaned_Name column locally first
    df['Cleaned_Name'] = df['Name'].apply(get_api_name)

    # Initialize Excel Writer
    writer = pd.ExcelWriter(OUTPUT_FILE, engine='xlsxwriter')
    workbook = writer.book
    worksheet = workbook.add_worksheet('Sheet1')

    # Define Formats
    header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1})
    center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})

    # Write Headers
    headers = ['Sprite', 'Name', 'Cleaned_Name', 'Tier']
    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header, header_fmt)

    # Set Column Widths
    worksheet.set_column('A:A', 14)  # Sprite column
    worksheet.set_column('B:C', 25)  # Name columns
    worksheet.set_column('D:D', 10)  # Tier column

    print(f"Fetching sprites for {len(df)} Pokémon...")

    for index, row in df.iterrows():
        row_num = index + 1
        worksheet.set_row(row_num, 60)  # Set height for image

        # Write Text Data
        worksheet.write(row_num, 1, row['Name'], center_fmt)
        worksheet.write(row_num, 2, row['Cleaned_Name'], center_fmt)
        worksheet.write(row_num, 3, row['Tier'], center_fmt)

        # Fetch Image
        api_name = row['Cleaned_Name']
        try:
            url = f"https://pokeapi.co/api/v2/pokemon/{api_name}"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                img_url = data['sprites']['front_default']

                if img_url:
                    img_data = requests.get(img_url).content
                    image_stream = io.BytesIO(img_data)

                    worksheet.insert_image(row_num, 0, api_name, {
                        'image_data': image_stream,
                        'x_scale': 0.7, 'y_scale': 0.7,
                        'object_position': 1
                    })
                    print(f"[{index + 1}] Success: {row['Name']}")
                else:
                    worksheet.write(row_num, 0, "No Sprite", center_fmt)
            else:
                # If 404, it might be a custom/fan-made Pokemon
                worksheet.write(row_num, 0, "Not Found", center_fmt)
                print(f"[{index + 1}] 404 Not Found: {api_name}")

        except Exception as e:
            print(f"Error fetching {row['Name']}: {e}")

    writer.close()
    print(f"\nDone! Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()