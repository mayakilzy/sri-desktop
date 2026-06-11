import uvicorn
import sys
import os

# أضف مسار الـ backend لـ Python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

if __name__ == '__main__':
    uvicorn.run("app:app", host="127.0.0.1", port=3011, reload=False)
