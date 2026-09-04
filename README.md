# Dam Break Decision Support System (SIH26161)

## Local Run Instructions

### Prerequisites
- Conda (Miniforge / Anaconda)
- Node.js (v20+) and npm

### 1. Conda Environment Setup
```powershell
conda env create -f environment.yml
conda activate sih-app
```

### 2. Backend Service (FastAPI)
```powershell
cd backend
pytest -v
uvicorn app.main:app --reload --port 8000
```
- Health Check: `http://localhost:8000/api/health`
- Interactive API Docs: `http://localhost:8000/docs`

### 3. Frontend Application (React + Vite + TypeScript)
```powershell
cd frontend
npm install
npm run build
npm run dev
```
- Web Application: `http://localhost:5173`

### 4. Optional Convenience Script
```powershell
.\scripts\dev.ps1
```
