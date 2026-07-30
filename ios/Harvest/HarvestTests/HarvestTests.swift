import Testing
@testable import Harvest

struct HarvestTests {
    @Test func materialDecodesSentenceTimeline() throws {
        let data = """
        {"id":1,"title":"雨の日","status":"ready","error_message":null,"duration_ms":1500,"audio_url":"https://example.com/a.mp3","segments":[{"id":9,"material_id":1,"idx":0,"text_ja":"雨です。","text_zh":null,"start_ms":0,"end_ms":1500}]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: data)
        #expect(material.segments[0].startMs == 0)
        #expect(material.segments[0].endMs == 1_500)
    }
}
