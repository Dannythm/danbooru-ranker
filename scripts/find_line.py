
with open(r'h:/MEGA/AG/Artists_Gens.html', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'Pictoric' in line:
            print(f'Found at line {i+1}: {line[:100]}...')
