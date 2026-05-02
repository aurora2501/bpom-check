from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# In-memory cache: {product_name: {'data': result, 'timestamp': time}}
CACHE = {}
CACHE_TTL = 3600  # 1 hour in seconds

# Harmful ingredients database (rule-based detection)
HARMFUL_INGREDIENTS = {
    'mercury': ['merkuri', 'raksa', 'air raksa'],
    'lead': ['timbal', 'pb'],
    'cadmium': ['kadmium', 'cd'],
    'arsenic': ['arsen', 'as'],
    'hydroquinone': ['hidrokuinon', 'hydroquinone'],
    'kojic': ['kojik acid', 'kojic', 'asam kojik'],
    'calomel': ['kalomel', 'calomel'],
    'corticosteroid': ['kortikosteroid', 'deksametason', 'prednison'],
    'antibiotic': ['antibiotik', 'tetracycline', 'aminoglikosida'],
    'steroid': ['steroid', 'hormon']
}

def normalize_keyword(keyword):
    """Normalize product name for better search results"""
    return keyword.lower().strip()

def is_cache_valid(cached_time):
    """Check if cache entry is still valid"""
    return datetime.now() - cached_time < timedelta(seconds=CACHE_TTL)

def get_from_cache(product_name):
    """Retrieve product from cache if valid"""
    normalized = normalize_keyword(product_name)
    if normalized in CACHE:
        cached_entry = CACHE[normalized]
        if is_cache_valid(cached_entry['timestamp']):
            return cached_entry['data']
        else:
            del CACHE[normalized]
    return None

def save_to_cache(product_name, data):
    """Save product data to cache"""
    normalized = normalize_keyword(product_name)
    CACHE[normalized] = {
        'data': data,
        'timestamp': datetime.now()
    }

def scrape_bpom(product_name):
    """
    Scrape BPOM website for product information
    Returns dict with product details or None if not found
    """
    try:
        # Check cache first
        cached_result = get_from_cache(product_name)
        if cached_result:
            cached_result['dari_cache'] = True
            return cached_result
        
        url = "https://cekbpom.pom.go.id/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Prepare payload for BPOM search
        payload = {
            'yt0': '',  # Search button
            'YiiAjaxRequest': 'ajax',
        }
        
        # BPOM uses POST request with specific parameters
        params = {
            'namaProduk': product_name,
            'nomorRegistrasi': '',
            'tipeSearchBy': 'namaProduk'
        }
        
        response = requests.post(
            url,
            data=params,
            headers=headers,
            timeout=10,
            allow_redirects=True
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Try to find the results table
        table = soup.find('table', {'class': 'table'})
        
        if not table:
            # Try alternative table classes
            table = soup.find('table')
        
        if not table:
            return {
                'status': 'not_found',
                'pesan': f'Produk "{product_name}" tidak ditemukan di database BPOM',
                'dari_cache': False
            }
        
        # Extract rows from table
        rows = table.find_all('tr')[1:]  # Skip header row
        
        if not rows:
            return {
                'status': 'not_found',
                'pesan': f'Produk "{product_name}" tidak ditemukan di database BPOM',
                'dari_cache': False
            }
        
        results = []
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 6:
                try:
                    product_info = {
                        'nama_produk': cols[0].get_text(strip=True),
                        'nomor_registrasi': cols[1].get_text(strip=True),
                        'pabrik': cols[2].get_text(strip=True),
                        'tipe_produk': cols[3].get_text(strip=True),
                        'status': 'Terdaftar',
                    }
                    
                    # Analyze for harmful ingredients
                    harmful_found = analyze_harmful_ingredients(product_info['nama_produk'])
                    if harmful_found:
                        product_info['warning'] = harmful_found
                    
                    results.append(product_info)
                except (IndexError, AttributeError):
                    continue
        
        if results:
            data = {
                'status': 'found',
                'total_hasil': len(results),
                'produk': results,
                'dari_cache': False
            }
            save_to_cache(product_name, data)
            return data
        else:
            return {
                'status': 'not_found',
                'pesan': f'Produk "{product_name}" tidak ditemukan di database BPOM',
                'dari_cache': False
            }
    
    except requests.exceptions.ConnectionError:
        return {
            'status': 'error',
            'pesan': 'Gagal terhubung ke website BPOM. Periksa koneksi internet Anda.',
            'dari_cache': False
        }
    except requests.exceptions.Timeout:
        return {
            'status': 'error',
            'pesan': 'Request timeout. Website BPOM tidak merespons dalam waktu yang ditentukan.',
            'dari_cache': False
        }
    except Exception as e:
        return {
            'status': 'error',
            'pesan': f'Terjadi kesalahan saat mengakses BPOM: {str(e)}',
            'dari_cache': False
        }

def analyze_harmful_ingredients(product_name):
    """
    Analyze product name for potentially harmful ingredients
    Returns list of detected harmful substances or empty list
    """
    product_lower = product_name.lower()
    detected = []
    
    for category, keywords in HARMFUL_INGREDIENTS.items():
        for keyword in keywords:
            if keyword in product_lower:
                detected.append(category)
                break
    
    return list(set(detected))

@app.route('/')
def index():
    """Render main page"""
    return render_template('index.html')

@app.route('/cek')
def cek_api():
    """
    API endpoint for checking BPOM product registration
    GET /cek?produk=<product_name>
    """
    product_name = request.args.get('produk', '').strip()
    
    if not product_name:
        return jsonify({
            'status': 'error',
            'pesan': 'Parameter "produk" harus diisi'
        }), 400
    
    if len(product_name) < 2:
        return jsonify({
            'status': 'error',
            'pesan': 'Nama produk minimal 2 karakter'
        }), 400
    
    result = scrape_bpom(product_name)
    return jsonify(result)

@app.route('/search', methods=['POST'])
def search():
    """
    POST endpoint for form submission
    Accepts JSON: {"produk": "product_name"}
    """
    try:
        data = request.get_json() or request.form
        product_name = data.get('produk', '').strip()
        
        if not product_name:
            return jsonify({
                'status': 'error',
                'pesan': 'Nama produk harus diisi'
            }), 400
        
        if len(product_name) < 2:
            return jsonify({
                'status': 'error',
                'pesan': 'Nama produk minimal 2 karakter'
            }), 400
        
        result = scrape_bpom(product_name)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'pesan': f'Terjadi kesalahan: {str(e)}'
        }), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cache_size': len(CACHE)
    })

@app.route('/cache/stats')
def cache_stats():
    """Cache statistics endpoint"""
    stats = {
        'total_cached': len(CACHE),
        'cached_products': list(CACHE.keys()),
        'cache_ttl_seconds': CACHE_TTL
    }
    return jsonify(stats)

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clear cache endpoint"""
    CACHE.clear()
    return jsonify({'status': 'success', 'pesan': 'Cache berhasil dihapus'})

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({'status': 'error', 'pesan': 'Endpoint tidak ditemukan'}), 404

@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors"""
    return jsonify({'status': 'error', 'pesan': 'Terjadi kesalahan pada server'}), 500

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )