<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Property Analytics System</title>
    <link rel="icon" type="image/svg+xml" href="{{ asset('favicon.svg') }}">
    <link rel="alternate icon" href="{{ asset('favicon.ico') }}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            background-color: #17072b;
            color: #ffffff;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(138, 43, 226, 0.45) 0%, transparent 40%),
                radial-gradient(circle at 85% 15%, rgba(220, 200, 140, 0.4) 0%, transparent 35%),
                radial-gradient(circle at 90% 65%, rgba(215, 185, 120, 0.35) 0%, transparent 40%),
                radial-gradient(circle at 75% 85%, rgba(180, 120, 240, 0.35) 0%, transparent 45%),
                radial-gradient(circle at 20% 85%, rgba(75, 0, 130, 0.4) 0%, transparent 40%);
            background-size: cover;
            background-attachment: fixed;
        }

        /* Ambient Glow Blobs mimicking the screenshot */
        .ambient-blob {
            position: absolute;
            filter: blur(80px);
            opacity: 0.65;
            pointer-events: none;
            z-index: 1;
            border-radius: 50%;
        }

        .blob-1 {
            width: 380px;
            height: 380px;
            top: -50px;
            left: -50px;
            background: radial-gradient(circle, rgba(147, 51, 234, 0.5) 0%, rgba(79, 70, 229, 0.2) 70%);
        }

        .blob-2 {
            width: 460px;
            height: 460px;
            top: -20px;
            right: -60px;
            background: radial-gradient(circle, rgba(234, 215, 160, 0.45) 0%, rgba(192, 132, 252, 0.3) 60%);
        }

        .blob-3 {
            width: 520px;
            height: 520px;
            bottom: -80px;
            right: -30px;
            background: radial-gradient(circle, rgba(216, 180, 254, 0.4) 0%, rgba(245, 208, 144, 0.35) 50%, rgba(79, 70, 229, 0.1) 80%);
        }

        .blob-4 {
            width: 400px;
            height: 400px;
            bottom: -50px;
            left: 10%;
            background: radial-gradient(circle, rgba(91, 33, 182, 0.5) 0%, rgba(139, 92, 246, 0.2) 70%);
        }

        /* Top Header */
        .top-nav {
            position: relative;
            z-index: 10;
            padding: 2.25rem 3rem;
            display: flex;
            align-items: center;
            justify-content: flex-start;
        }

        .globe-icon {
            width: 40px;
            height: 40px;
            stroke: rgba(255, 255, 255, 0.85);
            stroke-width: 1.25;
            fill: none;
            opacity: 0.9;
            transition: transform 0.4s ease, opacity 0.3s ease;
        }

        .globe-icon:hover {
            opacity: 1;
            transform: rotate(20deg) scale(1.05);
        }

        /* Main Center Content */
        .hero-container {
            position: relative;
            z-index: 10;
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem 1.5rem;
            text-align: center;
            max-width: 1100px;
            margin: 0 auto;
            width: 100%;
        }

        .hero-title {
            font-size: clamp(2.5rem, 5.5vw, 4.5rem);
            font-weight: 700;
            line-height: 1.12;
            letter-spacing: -0.03em;
            color: #ffffff;
            margin-bottom: 3.5rem;
            text-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
            max-width: 860px;
        }

        /* Action Buttons Row */
        .action-group {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            align-items: center;
            gap: 1.5rem;
            width: 100%;
            max-width: 820px;
        }

        .action-btn {
            display: inline-flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-width: 210px;
            height: 64px;
            padding: 0.75rem 1.75rem;
            border-radius: 4px;
            border: 1.5px solid rgba(255, 255, 255, 0.65);
            background: rgba(255, 255, 255, 0.04);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            color: #ffffff;
            text-decoration: none;
            font-size: 1.05rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            line-height: 1.25;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2);
        }

        .action-btn:hover {
            border-color: #ffffff;
            background: rgba(255, 255, 255, 0.16);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(255, 255, 255, 0.12), 0 4px 16px rgba(0, 0, 0, 0.35);
        }

        .action-btn:active {
            transform: translateY(0);
        }

        .action-btn.placeholder {
            border-color: rgba(255, 255, 255, 0.45);
            color: rgba(255, 255, 255, 0.9);
            cursor: pointer;
        }

        .action-btn.placeholder:hover {
            border-color: rgba(255, 255, 255, 0.75);
            background: rgba(255, 255, 255, 0.1);
        }

        .badge-placeholder {
            display: block;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(255, 255, 255, 0.6);
            margin-top: 2px;
        }

        /* Bottom spacer / footer */
        .footer-space {
            height: 3rem;
        }

        /* Toast notification for placeholders */
        .placeholder-toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: rgba(20, 10, 35, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(12px);
            color: #ffffff;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 0.9rem;
            font-weight: 500;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s ease;
            z-index: 100;
        }

        .placeholder-toast.show {
            transform: translateY(0);
            opacity: 1;
        }
    </style>
</head>
<body>

    <!-- Ambient Gradient Blobs mimicking the background -->
    <div class="ambient-blob blob-1"></div>
    <div class="ambient-blob blob-2"></div>
    <div class="ambient-blob blob-3"></div>
    <div class="ambient-blob blob-4"></div>

    <!-- Top Left Globe Wireframe -->
    <header class="top-nav">
        <svg class="globe-icon" viewBox="0 0 24 24" stroke="currentColor">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path>
            <path d="M2 12h20"></path>
            <path d="M4 7h16"></path>
            <path d="M4 17h16"></path>
        </svg>
    </header>

    <!-- Main Hero Center Section -->
    <main class="hero-container">
        <h1 class="hero-title">
            Smart Property<br>
            Analytics System
        </h1>

        <div class="action-group">
            <a href="{{ route('analytics.dashboard') }}" class="action-btn">
                <span>Analytics</span>
                <span>Dashboard</span>
            </a>

            <a href="{{ route('forecast.index') }}" class="action-btn">
                <span>Forecasting</span>
                <span>Pipeline</span>
            </a>

            <a href="{{ route('scraping.index') }}" class="action-btn">
                <span>OTA Scraping</span>
                <span>Demo</span>
            </a>
        </div>
    </main>

    <div class="footer-space"></div>

    <div id="toast" class="placeholder-toast"></div>

    <script>
        function showPlaceholderNotice(featureName) {
            const toast = document.getElementById('toast');
            toast.textContent = featureName + ' will be available in the upcoming release.';
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }
    </script>
</body>
</html>
