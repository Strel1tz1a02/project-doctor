package com.example.slowquery.mapper;

import com.example.slowquery.model.ExportRow;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ExportRowMapper {

    @Select("SELECT id, segment, amount, created_at_ms FROM export_rows ORDER BY id LIMIT #{chunks}")
    List<ExportRow> findRows(@Param("chunks") int chunks);
}
