package com.example.slowquery.mapper;

import com.example.slowquery.model.Section;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface SectionMapper {

    @Select("SELECT id, course_id, title, created_at_ms FROM sections ORDER BY created_at_ms DESC LIMIT #{size}")
    List<Section> findRecentSections(@Param("size") int size);

    @Select("SELECT title FROM courses WHERE id = #{courseId}")
    String findCourseTitleById(@Param("courseId") long courseId);

    @Select("SELECT COUNT(*) FROM resources WHERE section_id = #{sectionId}")
    long countResourcesBySectionId(@Param("sectionId") long sectionId);
}
