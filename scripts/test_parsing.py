
import os
from bs4 import BeautifulSoup

HTML_FILE = r'h:/MEGA/AG/Artists_Gens.html'

def parse_artists_gens():
    if not os.path.exists(HTML_FILE):
        print(f"File not found: {HTML_FILE}")
        return

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    categories = {}
    
    # Find all h3 headers which seem to be the categories
    headers = soup.find_all('h3')
    
    for h3 in headers:
        category_name = h3.get_text(strip=True).replace('¶', '').strip()
        print(f"Found category: {category_name}")
        
        # Debug: check next siblings
        curr = h3.next_sibling
        found_table = False
        for _ in range(5): # Check next 5 siblings
            if curr:
                print(f"  - Sibling: {curr.name} (Type: {type(curr)})")
                if curr.name == 'table':
                    found_table = True
                    break
                curr = curr.next_sibling
            else:
                break
        
        if found_table:
            next_node = curr
        else:
            next_node = None
            
        if next_node and next_node.name == 'table':
            rows = next_node.find_all('tr')
            print(f"  - Found {len(rows)} artists")
            
            for row in rows:
                cols = row.find_all('td')
                if cols:
                    # First col is artist name/link
                    link = cols[0].find('a')
                    if link:
                        artist_name = link.get_text(strip=True)
                        categories[artist_name] = category_name
                        # print(f"    - {artist_name}")

    print(f"\nTotal artists mapped: {len(categories)}")
    return categories

if __name__ == '__main__':
    parse_artists_gens()
