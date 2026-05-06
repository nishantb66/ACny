from django.test import SimpleTestCase


class HealthTests(SimpleTestCase):
    def test_health_endpoint(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
