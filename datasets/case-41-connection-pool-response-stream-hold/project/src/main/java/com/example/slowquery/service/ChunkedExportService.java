package com.example.slowquery.service;

import com.example.slowquery.dto.ExportStreamSummaryVO;
import com.example.slowquery.mapper.ExportRowMapper;
import com.example.slowquery.model.ExportRow;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

@Service
public class ChunkedExportService {

    private final ExportRowMapper exportRowMapper;

    public ChunkedExportService(ExportRowMapper exportRowMapper) {
        this.exportRowMapper = exportRowMapper;
    }

    @Transactional
    public ExportStreamSummaryVO streamChunked(int chunks, OutputStream out) throws IOException {
        List<ExportRow> rows = exportRowMapper.findRows(chunks);
        long written = 0L;
        for (ExportRow row : rows) {
            byte[] line = formatChunk(row).getBytes(StandardCharsets.UTF_8);
            out.write(line);
            out.flush();
            written += line.length;
        }
        return new ExportStreamSummaryVO(rows.size(), written);
    }

    private String formatChunk(ExportRow row) {
        long acc = 0L;
        for (int i = 0; i < 2000; i++) {
            acc += (row.getAmount() * 31 + i) % 11;
        }
        return row.getSegment() + "," + (row.getAmount() + acc) + "\n";
    }
}
