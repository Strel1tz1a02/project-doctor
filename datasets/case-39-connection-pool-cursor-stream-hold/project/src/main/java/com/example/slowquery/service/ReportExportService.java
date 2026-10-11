package com.example.slowquery.service;

import com.example.slowquery.dto.ReportExportResultVO;
import com.example.slowquery.mapper.ReportRowMapper;
import com.example.slowquery.model.ReportRow;
import org.apache.ibatis.cursor.Cursor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ReportExportService {

    private final ReportRowMapper reportRowMapper;

    public ReportExportService(ReportRowMapper reportRowMapper) {
        this.reportRowMapper = reportRowMapper;
    }

    @Transactional
    public ReportExportResultVO streamExport(int limit) {
        StringBuilder sink = new StringBuilder();
        int exported = 0;
        try (Cursor<ReportRow> cursor = reportRowMapper.streamRows(limit)) {
            for (ReportRow row : cursor) {
                sink.append(formatRow(row));
                exported++;
            }
        } catch (Exception e) {
            throw new IllegalStateException("导出失败", e);
        }
        return new ReportExportResultVO(limit, exported, sink.length());
    }

    private String formatRow(ReportRow row) {
        long acc = 0L;
        for (int i = 0; i < 3000; i++) {
            acc += (row.getAmount() * 31 + i) % 7;
        }
        return row.getRegion() + "," + row.getMetric() + "," + (row.getAmount() + acc) + "\n";
    }
}
