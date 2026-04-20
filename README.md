# Flickr Duplicate Cleaner 🔍

A web application to find, compare, and remove visual duplicates from your Flickr library. Unlike simple filename matchers, this tool uses **Perceptual Hashing (pHash)** to find images that look the same even if they have different resolutions, compression, or missing metadata.

## Key Features

- **Visual Comparison**: Uses pHash to find visual similarities regardless of file size or format.
- **Choice-Based Review**: See photo resolutions (Width x Height & MP) side-by-side and choose exactly which version to keep.
- **Deep Scan Mode**: Optionally ignore photo dates to find duplicates across your entire library (great for catching unsynced WhatsApp copies).
- **Scalable Caching**: Persistent SQLite database ensures photos are only hashed once, making subsequent scans nearly instant.
- **Parallel Processing**: Multi-threaded scanner speeds up the initial processing of large libraries.
- **Public Ready & Secure**: Built with `python-dotenv` to keep your Flickr API secrets safe and out of your public repository.

## Getting Started

### 1. Prerequisites

- Python 3.10+
- A [Flickr API Key](https://www.flickr.com/services/apps/create/) (Key & Secret)

### 2. Installation

1. Clone the repository:
   ```bash
   git clone <your-repo-url>
   cd flickr-duplicate-cleaner
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv env
   source env/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: You can also use the existing tools if you are running locally).*

### 3. Configuration

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and provide your Flickr API credentials:
   ```ini
   FLICKR_API_KEY=your_key_here
   FLICKR_API_SECRET=your_secret_here
   ```

## Usage

1. **Launch the Server**:
   ```bash
   python3 -m flask run
   ```
2. **Access the UI**: Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser.
3. **Authenticate**: Follow the prompt to authorize the app on your Flickr account.
4. **Scan**: Choose your similarity threshold and click **Find & Compare**.
5. **Resolve**: Review the highlighted pairs and choose which version to **DELETE**.

## Technology Stack

- **Backend**: Flask, flickrapi
- **Image Processing**: Pillow, ImageHash
- **Storage**: SQLite3
- **Frontend**: Modern Vanilla CSS, Asynchronous JavaScript

## Author

**Marco D'Amico**
Web: [marcodamico.github.io](https://marcodamico.github.io)
Email: [marcodamico@protonmail.com](mailto:marcodamico@protonmail.com)

&copy; 2026 Marco D'Amico. All rights reserved.

---