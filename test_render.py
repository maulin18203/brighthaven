from app import app, LEGACY_ROOMS
from flask import session

with app.test_request_context():
    from flask import render_template
    try:
        html = render_template('users/dashboard.html', 
                               user={'name': 'Test User', 'username': 'test'},
                               rooms=LEGACY_ROOMS,
                               total=20,
                               on_count=5,
                               scenes=[])
        print("RENDER_SUCCESS")
    except Exception as e:
        import traceback
        traceback.print_exc()
