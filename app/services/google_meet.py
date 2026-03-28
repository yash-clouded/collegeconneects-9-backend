import datetime
import uuid
from google.oauth2 import service_account
from googleapiclient.discovery import build
from app.config import settings

class GoogleMeetService:
    def __init__(self):
        self.scopes = ['https://www.googleapis.com/auth/calendar']
        self.creds = None
        if settings.google_application_credentials:
            self.creds = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials, scopes=self.scopes
            )
            if hasattr(settings, 'google_impersonate_user') and settings.google_impersonate_user:
                self.creds = self.creds.with_subject(settings.google_impersonate_user)
        self.service = build('calendar', 'v3', credentials=self.creds) if self.creds else None

    def create_meeting(self, summary: str, start_time: datetime.datetime, end_time: datetime.datetime, attendees: list[str]):
        if not self.service:
            print("Google Calendar service not initialized. Check credentials.")
            return None

        event = {
            'summary': summary,
            'description': 'CollegeConnect Session',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': [{'email': email} for email in attendees],
            'conferenceData': {
                'createRequest': {
                    'requestId': str(uuid.uuid4()),
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
        }

        created_event = self.service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1
        ).execute()

        return {
            'event_id': created_event.get('id'),
            'meet_link': created_event.get('hangoutLink')
        }

google_meet_service = GoogleMeetService()
