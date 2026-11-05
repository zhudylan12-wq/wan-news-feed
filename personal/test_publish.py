import json
import unittest
from publish import public_payload

class PublicMetadataTests(unittest.TestCase):
    def sample(self):
        return {'schemaVersion':1,'status':'ok','collectedAt':'2026-11-05T12:00:00+08:00',
                'newestPublishedAt':'2026-11-04T21:00:07+08:00',
                'items':[{'id':'youtube-WoeDaIg7Xf4','remoteId':'WoeDaIg7Xf4',
                          'sourceId':'aespa-youtube','artist':'aespa','verified':True,
                          'title':'aespa Concert Behind','url':'https://www.youtube.com/watch?v=WoeDaIg7Xf4'}],
                'sources':[{'id':'aespa-youtube','status':'ok'}]}
    def test_only_public_metadata_fields_can_leave_local_machine(self):
        data=self.sample()
        data['apiKey']='must-stay-local';data['personalNotes']=['private'];data['items'][0]['token']='private-token';data['sources'][0]['privateContact']='private'
        result=public_payload(data);raw=json.dumps(result)
        for secret in ['must-stay-local','private-token','privateContact','personalNotes']:
            self.assertNotIn(secret,raw)
        self.assertEqual(len(result['items']),len(data['items']))
    def test_account_reassignment_is_not_publishable(self):
        data=self.sample();data['items'][0]['artist']='other'
        with self.assertRaises(ValueError):public_payload(data)

if __name__=='__main__':unittest.main()
