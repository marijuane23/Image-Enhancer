# Lumix 4K Image Enhancer — Frontend Client

A modern, responsive web application for Lumix AI 4K Image Enhancer built with vanilla HTML5, CSS3, and JavaScript. Features sleek obsidian glassmorphism aesthetics, drag-and-drop image uploads, real-time asynchronous job polling, and an interactive Before/After comparison slider.

---

## 🛠️ Prerequisites

- Any modern web browser: **Google Chrome**, **Mozilla Firefox**, **Microsoft Edge**, or **Apple Safari**.
- A local static HTTP server (Python, Node.js, or VS Code extension).

> **Important:** To avoid browser cross-origin policy restrictions with local files (`file://`), serve the frontend over an HTTP server (`http://localhost:3000`).

---

## 🚀 How to Run Locally

You can serve the frontend files using any of the following lightweight methods:

### Method 1: Using Python (Recommended if Python is installed)

**From the repository root:**
```bash
python -m http.server 3000 --directory frontend
```

**Or navigate inside the `frontend/` folder:**
```bash
cd frontend
python -m http.server 3000
```
*(On Windows, use `py -m http.server 3000` if `python` is not in your PATH).*

Open your browser at: **`http://localhost:3000`**

---

### Method 2: Using Node.js (`npx serve` or `http-server`)

If you have Node.js installed:

```bash
cd frontend
npx -y serve -l 3000
```
*or*
```bash
cd frontend
npx -y http-server -p 3000
```

Open your browser at: **`http://localhost:3000`**

---

### Method 3: Using VS Code "Live Server" Extension

1. Open the project folder in **Visual Studio Code**.
2. Install the **Live Server** extension (`ritwickdey.liveserver`).
3. Right-click [`frontend/index.html`](file:///c:/Users/Kevin/Documents/Image-Enhancer/frontend/index.html) and select **"Open with Live Server"**.

---

## 🔗 Connecting to the Backend

1. Make sure your backend server is running (defaults to `http://127.0.0.1:8000`).
2. The frontend automatically performs health checks to verify connectivity.
   - **Online Badge (Green)**: Connected and ready to process images.
   - **Offline Badge (Red)**: Backend not detected.
3. **Change Backend URL**:
   - Click on the status badge or the **gear icon** in the top navigation bar.
   - Enter your backend URL (e.g. `http://127.0.0.1:8000` for local dev or `https://your-app.onrender.com` for production).
   - Click **"Test Connection"** to verify live connectivity, then click **"Save"**.
   - The selected URL is persisted in your browser's `localStorage`.

---

## 🌟 Key UI Features

- **Drag-and-Drop Dropzone**: Select or drag JPG, PNG, or WebP files up to 10MB.
- **Real-Time Job Progress Tracker**: Polls `GET /status/{job_id}` every 2 seconds with an animated progress bar and detailed stage updates.
- **Interactive Before/After Comparison Slider**:
  - **Mouse Drag**: Drag the central divider across the image container.
  - **Touch Swipe**: Drag effortlessly on mobile or touchscreen devices.
  - **Click to Jump**: Click anywhere along the image to instantly position the slider.
  - **Keyboard Accessible**: Focus the handle and use `ArrowLeft` / `ArrowRight` keys.
- **One-Click 4K Download**: Download the enhanced image with an ASCII-sanitized `-4k` filename.

---

## 📁 File Structure

```
frontend/
├── index.html     # Semantic markup, dropzone, comparison slider stage, modal
├── style.css      # Dark glassmorphism, responsive layout, fluid slider styling
├── app.js         # API polling, health checks, drag-and-drop, slider interactions
└── README.md      # Frontend local run documentation
```
