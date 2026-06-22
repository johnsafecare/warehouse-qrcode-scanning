import sys
sys.path.append('c:\\Users\\admin\\Desktop\\QR 15-6-2 - Copy')
from qr_system import app

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user'] = 'testuser'
    res = c.get('/api/activity-logs')
    print(res.get_json())
