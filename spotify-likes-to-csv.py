import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
import sys

CLIENT_ID = 'CHANGEME' 
CLIENT_SECRET = 'CHANGEME'
REDIRECT_URI = 'http://127.0.0.1:8888/callback'

def main():
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope="user-library-read"
        ))

        print("Autenticado. Descargando...")
        
        results = sp.current_user_saved_tracks(limit=50)
        tracks_data = []
        
        while results:
            for item in results['items']:
                track = item['track']
                
                track_info = {
                    'Song': track['name'],
                    'Artist': track['artists'][0]['name'],
                    'Album': track['album']['name'],
                    'ISRC': track['external_ids'].get('isrc', '')
                }
                tracks_data.append(track_info)
            
            if results['next']:
                results = sp.next(results)
                sys.stdout.write(f"\rProcesadas: {len(tracks_data)}")
                sys.stdout.flush()
            else:
                results = None

        df = pd.DataFrame(tracks_data)
        
        df = df[['Song', 'Artist', 'Album', 'ISRC']]
        
        df.to_csv('spotify_likes.csv', index=False, encoding='utf-8')
        print(f"\n\n[OK] Archivo 'spotify_likes.csv' generado con {len(tracks_data)} filas.")
        print("Columnas: Song, Artist, Album, ISRC")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
