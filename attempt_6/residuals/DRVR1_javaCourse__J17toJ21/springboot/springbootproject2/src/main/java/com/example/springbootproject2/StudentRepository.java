package com.example.springbootproject2;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Repository
@AllArgsConstructor
@NoArgsConstructor
@Data
public class StudentRepository {

    @Autowired
    private JdbcTemplate jdbc;

    public void save(Student student) {
        System.out.println("[Repo] Saving student: " + student.getName());
        String query = "insert into student (id, name, avg) values (?,?,?)";
        jdbc.update(query, student.getId(), student.getName(), student.getAvg());
    }

    public List<Student> getAll() {
        String query = "select * from student";

        RowMapper<Student> rowMapper = new RowMapper<Student>() {
            @Override
            public Student mapRow(ResultSet rs, int rowNum) throws SQLException {
                Student s = new Student();
                s.setId(rs.getInt("id"));
                s.setName(rs.getString("name"));
                s.setAvg(rs.getInt("avg"));

                return s;
            }
        };
        return jdbc.query(query, rowMapper);
    }
}
