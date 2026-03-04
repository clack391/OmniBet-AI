import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(dotenv_path='.env')

def test_sdk():
    print("Testing SDK for Search Grounding...")
    # try picking up key automatically
    client = genai.Client()
    
    prompt = "Search Google for the exact SofaScore.com match URL for the football game between Hamburger SV and RB Leipzig. Return ONLY the raw URL string starting with 'https://www.sofascore.com' and nothing else. Output NOT_FOUND if you cannot find it."
    
    try:
        # Use gemini-2.5-flash for speed
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"googleSearch": {}}],
                temperature=0.0
            )
        )
        print(f"Result: {response.text}")
    except Exception as e:
        print(f"Fallback Error: {e}")
        try:
            # Fallback to gemini-2.0-flash
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"googleSearch": {}}],
                    temperature=0.0
                )
            )
            print(f"Fallback Result: {response.text}")
        except Exception as e2:
            print(f"Double Fallback Error: {e2}")

if __name__ == "__main__":
    test_sdk()
