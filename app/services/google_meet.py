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

    def create_actual_meeting_link(self, summary: str, start_time: datetime.datetime, end_time: datetime.datetime):
        """
        Creates a Google Meet link on the master calendar WITHOUT attendees.
        This keeps the link 'hidden' from the default calendar invitations.
        """
        if not self.service:
            return None

        event = {
            'summary': summary,
            'description': 'Private meeting space for CollegeConnect Session',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
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

    def create_placeholder_event(self, summary: str, start_time: datetime.datetime, end_time: datetime.datetime, attendees: list[str]):
        """
        Creates a calendar invitation for attendees WITHOUT a Meet link.
        Forces them to join via the CollegeConnect Dashboard.
        """
        if not self.service:
            return None

        # Format attendees for Google API
        attendee_list = [{'email': email} for email in attendees if email]

        event = {
            'summary': summary,
            'description': 'Please join the session through your CollegeConnect Dashboard 10 minutes before the scheduled time.\n\nDashboard: https://collegeconnect.co/dashboard',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': attendee_list,
            # IMPORTANT: We OMIT conferenceData here to keep the meet link hidden
        }

        return self.service.events().insert(
            calendarId='primary',
            body=event,
            sendUpdates='all' # Sends email invite
        ).execute()

    def create_meeting(self, summary: str, start_time: datetime.datetime, end_time: datetime.datetime, attendees: list[str]):
        # Legacy method kept for fallback
        return self.create_actual_meeting_link(summary, start_time, end_time)

google_meet_service = GoogleMeetService()
