import Foundation
import Testing
@testable import Harvest

struct HarvestTests {
    @Test func materialDecodesSentenceTimeline() throws {
        let data = """
        {"id":1,"kind":"reading","title":"雨の日","status":"ready","error_message":null,"duration_ms":1500,"audio_url":"https://example.com/a.mp3","video_url":null,"segments":[{"id":9,"material_id":1,"idx":0,"text_ja":"雨です。","text_zh":null,"start_ms":0,"end_ms":1500}],"tokens":[]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: data)
        #expect(material.segments[0].startMs == 0)
        #expect(material.segments[0].endMs == 1_500)
    }

    @Test func photoSubmissionDecodesMaterialContract() throws {
        let data = """
        {"material_id":41,"job_id":73,"status":"pending"}
        """.data(using: .utf8)!
        let submission = try JSONDecoder().decode(MaterialSubmission.self, from: data)
        #expect(submission.materialID == 41)
        #expect(submission.jobID == 73)
        #expect(submission.status == "pending")
    }

    @Test func shadowingAttemptDecodesAsyncStatus() throws {
        let data = """
        {"id":9,"asr_text":null,"diff_json":null,"score":null,"job_id":81,"status":"processing","error_message":null}
        """.data(using: .utf8)!
        let attempt = try JSONDecoder().decode(ShadowingAttempt.self, from: data)
        #expect(attempt.jobID == 81)
        #expect(attempt.status == "processing")
    }
}
