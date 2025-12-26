#!/usr/bin/env python3
"""
Test script to check webhook functionality
"""

import requests
import json
import os
from datetime import datetime

def test_webhook_endpoint():
    """Test the webhook endpoint directly"""
    print("🔍 Testing webhook endpoint...")

    # Try to get the webhook URL from environment or construct it
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        # Try to construct from Render URL
        render_url = os.getenv('RENDER_EXTERNAL_URL')
        if render_url:
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            if token:
                webhook_url = f"{render_url}/webhook/{token.split(':')[0]}"
                print(f"🔧 Constructed webhook URL: {webhook_url}")
            else:
                print("❌ No TELEGRAM_BOT_TOKEN found")
                return False
        else:
            print("❌ No RENDER_EXTERNAL_URL found")
            return False

    # Test webhook endpoint with a simple ping
    try:
        print(f"🌐 Testing webhook URL: {webhook_url}")

        # First test if the endpoint exists
        response = requests.get(webhook_url.replace('/webhook/', '/'), timeout=10)
        print(f"📡 Root endpoint status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"📄 Root response: {data}")

        # Test health endpoint
        health_url = webhook_url.replace('/webhook/', '/health')
        print(f"🏥 Testing health endpoint: {health_url}")
        response = requests.get(health_url, timeout=10)

        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ Health check successful")
            print(f"📊 Status: {health_data.get('status', 'unknown')}")
            print(f"🤖 Bot status: {health_data.get('bot_status', 'unknown')}")
            print(f"🗄️ Database: {health_data.get('database', {}).get('status', 'unknown')}")

            # Check if bot application is initialized
            bot_status = health_data.get('bot_status', 'unknown')
            if bot_status == 'unknown':
                print("⚠️ Bot status is unknown - application may not be initialized")
            else:
                print(f"✅ Bot status: {bot_status}")

        else:
            print(f"❌ Health check failed: {response.status_code}")
            print(f"Response: {response.text[:200]}...")

        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    """Main function"""
    print("Webhook Diagnostic Test")
    print("=" * 40)

    if test_webhook_endpoint():
        print("\n✅ Webhook endpoint test completed")
    else:
        print("\n❌ Webhook endpoint test failed")

if __name__ == "__main__":
    main()