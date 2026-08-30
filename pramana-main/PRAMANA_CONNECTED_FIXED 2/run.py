from backend.app import app, init_db
init_db()
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
