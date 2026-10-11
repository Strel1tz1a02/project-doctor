package com.example.slowquery.controller;

import com.example.slowquery.dto.ExportStreamSummaryVO;
import com.example.slowquery.service.ChunkedExportService;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;

@Slf4j
@RestController
@RequestMapping("/api/export")
public class ExportController {

    private final ChunkedExportService chunkedExportService;

    public ExportController(ChunkedExportService chunkedExportService) {
        this.chunkedExportService = chunkedExportService;
    }

    @GetMapping("/chunked-stream")
    public void chunkedStream(@RequestParam(defaultValue = "8000") int chunks,
                              HttpServletResponse response) throws IOException {
        response.setContentType("text/plain;charset=UTF-8");
        ExportStreamSummaryVO summary = chunkedExportService.streamChunked(chunks, response.getOutputStream());
        log.info("分块导出完成：exported={}, bytesWritten={}", summary.getExported(), summary.getBytesWritten());
    }
}
