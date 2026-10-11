package com.example.slowquery.controller;

import com.example.slowquery.dto.ReportExportResultVO;
import com.example.slowquery.service.ReportExportService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reports")
public class ReportController {

    private final ReportExportService reportExportService;

    public ReportController(ReportExportService reportExportService) {
        this.reportExportService = reportExportService;
    }

    @GetMapping("/stream-export")
    public ReportExportResultVO streamExport(@RequestParam(defaultValue = "20000") int limit) {
        return reportExportService.streamExport(limit);
    }
}
