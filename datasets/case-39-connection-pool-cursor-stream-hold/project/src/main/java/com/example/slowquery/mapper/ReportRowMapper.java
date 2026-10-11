package com.example.slowquery.mapper;

import com.example.slowquery.model.ReportRow;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.cursor.Cursor;
import org.apache.ibatis.session.ResultSetType;

@Mapper
public interface ReportRowMapper {

    @Select("SELECT id, region, metric, amount, created_at_ms FROM report_rows ORDER BY id LIMIT #{limit}")
    @Options(fetchSize = Integer.MIN_VALUE, resultSetType = ResultSetType.FORWARD_ONLY)
    Cursor<ReportRow> streamRows(@Param("limit") int limit);
}
